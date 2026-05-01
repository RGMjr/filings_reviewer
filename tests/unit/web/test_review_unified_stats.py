"""Smoke tests for the unified review Statistics page (/v2/review/stats).

The route was historically unreachable because it called DB methods that
no longer existed on DatabaseAdapter. These tests pin the route to its
current contract: it must render with both the empty-state and the
populated-state shapes returned by the per-metric DB methods.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


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
    with patch("src.web.routes.review_unified.get_db") as mock_get_db:
        mock = MagicMock()
        mock_get_db.return_value = mock
        yield mock


def _empty_text_data() -> dict:
    return {
        "per_company": [],
        "totals": {
            "filing_count": 0,
            "fact_count": 0,
            "reviewed_count": 0,
            "pending_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "corrected_count": 0,
            "auto_accepted_count": 0,
        },
        "confidence_bands": {
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "total_count": 0,
        },
    }


def test_stats_renders_empty(client, mock_db):
    mock_db.get_v2_review_stats.return_value = _empty_text_data()
    mock_db.get_image_decision_overall_v2.return_value = {
        "total_decisions": 0,
        "relevant_count": 0,
        "not_relevant_count": 0,
        "relevant_pct": 0.0,
        "not_relevant_pct": 0.0,
    }
    mock_db.get_image_review_progress_v2.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "auto_rejected_count": 0,
        "review_pct": 0.0,
    }
    mock_db.get_image_decisions_by_tier_v2.return_value = []
    mock_db.get_image_rejection_reasons_by_tier_v2.return_value = []

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Metric Analytics" in body
    # Empty-state alert in the images tab pane
    assert "No image review decisions yet" in body


def test_stats_renders_with_data(client, mock_db):
    mock_db.get_v2_review_stats.return_value = _empty_text_data()
    mock_db.get_image_decision_overall_v2.return_value = {
        "total_decisions": 10,
        "relevant_count": 7,
        "not_relevant_count": 3,
        "relevant_pct": 70.0,
        "not_relevant_pct": 30.0,
    }
    mock_db.get_image_review_progress_v2.return_value = {
        "total_candidates": 12,
        "pending_count": 2,
        "reviewed_count": 10,
        "skipped_count": 0,
        "auto_rejected_count": 0,
        "review_pct": 83.3,
    }
    mock_db.get_image_decisions_by_tier_v2.return_value = [
        {
            "detection_tier": "tier_1_cohort",
            "relevant_count": 5,
            "not_relevant_count": 1,
            "total_decisions": 6,
            "precision_pct": 83.3,
        },
        {
            "detection_tier": "tier_3_all",
            "relevant_count": 2,
            "not_relevant_count": 2,
            "total_decisions": 4,
            "precision_pct": 50.0,
        },
    ]
    mock_db.get_image_rejection_reasons_by_tier_v2.return_value = [
        {
            "detection_tier": "tier_3_all",
            "rejection_reason": "wrong_subject",
            "rejection_count": 2,
            "pct_of_tier_rejections": 100.0,
        },
    ]

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Decisions by Detection Tier" in body
    assert "Rejection Reasons by Detection Tier" in body
    # tier badge text rendered via |replace('_', ' ')|title
    assert "Tier 1 Cohort" in body
    assert "Tier 3 All" in body


def test_stats_does_not_swallow_db_errors(app, mock_db):
    """A DB regression should propagate, not be swallowed by a flash + redirect.

    The legacy try/except masked five missing DB methods for months by
    302-ing back to the filing list. This test pins the new contract:
    DB errors surface as real exceptions (which Flask converts to 500
    in production, but the testing client re-raises so the regression
    is loud in CI).
    """
    mock_db.get_v2_review_stats.side_effect = RuntimeError("schema regression")
    client = app.test_client()
    with pytest.raises(RuntimeError, match="schema regression"):
        client.get("/v2/review/stats")
