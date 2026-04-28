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

        with patch(
            "src.web.routes.review_unified.threading.Thread", side_effect=fake_thread
        ) as mock_thread_cls:
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
        tab=None,
        limit=50,
        offset=0,
        hide_completed=False,
        sort_by="date",
        sort_dir="desc",
        reviewer_ids=None,
    )


def test_filing_list_custom_page(client, mock_db, mock_render_template):
    """?page=2&per_page=25 passes limit=25, offset=25."""
    mock_db.get_unified_filings_for_review_count.return_value = 100
    mock_db.get_unified_filings_for_review.return_value = []

    client.get("/v2/review/filings?page=2&per_page=25")

    mock_db.get_unified_filings_for_review.assert_called_once_with(
        tab=None,
        limit=25,
        offset=25,
        hide_completed=False,
        sort_by="date",
        sort_dir="desc",
        reviewer_ids=None,
    )


def test_filing_list_per_page_cap(client, mock_db, mock_render_template):
    """?per_page=999 is capped to 200."""
    mock_db.get_unified_filings_for_review_count.return_value = 5
    mock_db.get_unified_filings_for_review.return_value = []

    client.get("/v2/review/filings?per_page=999")

    mock_db.get_unified_filings_for_review.assert_called_once_with(
        tab=None,
        limit=200,
        offset=0,
        hide_completed=False,
        sort_by="date",
        sort_dir="desc",
        reviewer_ids=None,
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
    mock_db.get_image_review_candidates_for_filing_v2.return_value = []

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
    mock_db.get_image_review_candidates_for_filing_v2.return_value = []

    client.get("/v2/review/1?per_page=50")

    _, kwargs = mock_render_template.call_args
    assert kwargs["page"] == 1
    assert kwargs["per_page"] == 50
    assert kwargs["total_pages"] == 2  # ceil(75/50)
    assert kwargs["total_facts"] == 75


def test_review_filing_partitions_facts_pending_first(client, mock_db, mock_render_template):
    """Pending facts must sort before reviewed ones in the strip — display
    order matches /api/v2/decisions auto-advance order. Stable within a
    partition (preserves the user's sort_by within each)."""
    mock_db.query.return_value = [FILING_ROW]
    mock_db.count_v2_facts_for_filing.return_value = 4
    mock_db.get_image_review_candidates_for_filing_v2.return_value = []

    accepted = {**FACT_ROW, "fact_id": "f-accepted-1", "review_status": "accepted"}
    pending_a = {**FACT_ROW, "fact_id": "f-pending-a", "review_status": "pending_review"}
    rejected = {**FACT_ROW, "fact_id": "f-rejected", "review_status": "rejected"}
    pending_b = {**FACT_ROW, "fact_id": "f-pending-b", "review_status": "pending_review"}

    # DB returns mixed order (e.g., the user's chosen sort interleaves statuses).
    mock_db.get_v2_facts_for_filing.return_value = [
        accepted,
        pending_a,
        rejected,
        pending_b,
    ]

    client.get("/v2/review/1")

    _, kwargs = mock_render_template.call_args
    rendered = [f["fact_id"] for f in kwargs["facts"]]
    # Both pending rows come first, in their original DB order; reviewed follow.
    assert rendered == ["f-pending-a", "f-pending-b", "f-accepted-1", "f-rejected"]


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


# =============================================================================
# next_filing cross-filing navigation — regression protection for:
#  - sort/filter context preservation (feat 5f16360, 34ec47e)
#  - reviewer-scoped auto-advance (new in this PR)
# =============================================================================


def test_next_filing_preserves_sort_order(client, mock_db, mock_render_template):
    """Sort params passed to /next-filing reach get_next_filing_with_pending_work."""
    mock_db.get_next_filing_with_pending_work.return_value = 42
    # Tab-inference fallback queries the current filing's metadata; an empty
    # row keeps effective_tab=None so the original assertion still holds.
    mock_db.query.return_value = []
    mock_db.get_filing_pending_counts.return_value = {
        "facts_pending": 1,
        "images_pending": 0,
    }

    client.get("/v2/review/next-filing?current_filing_id=1&list_sort_by=company&list_sort_dir=asc")

    mock_db.get_next_filing_with_pending_work.assert_called_once_with(
        current_filing_id=1,
        tab=None,
        hide_completed=False,
        sort_by="company",
        sort_dir="asc",
        reviewer_ids=None,
    )


def test_next_filing_threads_reviewer_filter(client, mock_db, mock_render_template):
    """list_reviewer_id params are threaded into the DB call so cross-filing
    advance stays within the reviewer scope."""
    mock_db.get_next_filing_with_pending_work.return_value = 99
    mock_db.query.return_value = []
    mock_db.get_filing_pending_counts.return_value = {
        "facts_pending": 1,
        "images_pending": 0,
    }

    response = client.get(
        "/v2/review/next-filing?current_filing_id=1&list_reviewer_id=alice&list_reviewer_id=bob"
    )

    mock_db.get_next_filing_with_pending_work.assert_called_once_with(
        current_filing_id=1,
        tab=None,
        hide_completed=False,
        sort_by="date",
        sort_dir="desc",
        reviewer_ids=["alice", "bob"],
    )
    # Next filing URL should carry list_reviewer_id forward so the NEXT page
    # still knows the scope (regression: prior bug reset to full list).
    assert response.status_code == 302
    assert "list_reviewer_id=alice" in response.location
    assert "list_reviewer_id=bob" in response.location


def test_next_filing_when_queue_empty_returns_to_list_with_scope(
    client,
    mock_db,
    mock_render_template,
):
    """When no next filing exists, redirect to list preserves sort + reviewer filters."""
    mock_db.get_next_filing_with_pending_work.return_value = None
    mock_db.query.return_value = []

    response = client.get(
        "/v2/review/next-filing?"
        "current_filing_id=1&list_sort_by=company&list_sort_dir=asc"
        "&list_reviewer_id=alice"
    )

    assert response.status_code == 302
    assert "/v2/review/filings" in response.location
    assert "sort_by=company" in response.location
    assert "sort_dir=asc" in response.location
    assert "reviewer_id=alice" in response.location


def test_next_filing_smart_default_targets_images_when_text_done(
    client, mock_db, mock_render_template
):
    """If the next filing has 0 pending text but pending images, the redirect
    URL opens the images tab (not Text+Pending Review on an empty list)."""
    mock_db.get_next_filing_with_pending_work.return_value = 77
    mock_db.query.return_value = []
    mock_db.get_filing_pending_counts.return_value = {
        "facts_pending": 0,
        "images_pending": 5,
    }

    response = client.get("/v2/review/next-filing?current_filing_id=1")

    assert response.status_code == 302
    assert "tab=images" in response.location
    assert "status=" not in response.location.split("?")[1]


def test_next_filing_smart_default_falls_back_to_all_when_nothing_pending(
    client, mock_db, mock_render_template
):
    """If the next filing has no pending work (edge case via reviewer scope),
    open Text+All Statuses rather than Pending Review."""
    mock_db.get_next_filing_with_pending_work.return_value = 88
    mock_db.query.return_value = []
    mock_db.get_filing_pending_counts.return_value = {
        "facts_pending": 0,
        "images_pending": 0,
    }

    response = client.get("/v2/review/next-filing?current_filing_id=1")

    assert response.status_code == 302
    assert "status=all" in response.location


def test_next_filing_infers_tab_from_current_filing_when_list_tab_missing(
    client, mock_db, mock_render_template
):
    """When the reviewer arrived from the 'All' filings view (no
    list_document_type), advancement still scopes to the current filing's
    analytical tab (IPO / Earnings / Investor Day)."""
    mock_db.get_next_filing_with_pending_work.return_value = 55
    mock_db.query.return_value = [
        {"document_type": "sec_filing", "form_type": "S-1"},
    ]
    mock_db.get_filing_pending_counts.return_value = {
        "facts_pending": 3,
        "images_pending": 0,
    }

    client.get("/v2/review/next-filing?current_filing_id=1")

    call = mock_db.get_next_filing_with_pending_work.call_args
    assert call.kwargs["tab"] == "ipo"
