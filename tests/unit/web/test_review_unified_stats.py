"""Smoke tests for the unified review Statistics page (/v2/review/stats).

The route was historically unreachable because it called DB methods that
no longer existed on DatabaseAdapter. These tests pin the route to its
current contract: it must render with both the empty-state and the
populated-state shapes returned by the per-metric DB methods.
"""

from datetime import UTC
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


def _stub_analytics_helpers(mock_db) -> None:
    """Set safe defaults for the Phase-2 + Phase-3 Summary-tab helpers.

    The Jinja template iterates these and reads `.length` / `.created_at`,
    so an unset MagicMock returns a non-iterable that crashes the render.
    Tests that need populated data override these explicitly.
    """
    mock_db.get_last_training_run.return_value = None
    mock_db.count_image_decisions_since.return_value = {
        "total": 0,
        "positive": 0,
        "negative": 0,
    }
    mock_db.count_text_decisions_since.return_value = 0
    mock_db.get_recent_text_corrections.return_value = []
    mock_db.get_recent_text_additions.return_value = []
    mock_db.get_recent_image_additions.return_value = []
    mock_db.get_recent_image_corrections.return_value = []
    # Phase 3: stats() now calls db.query() directly to check whether a retrain
    # is currently running. Default to "none running" so button gating depends
    # only on the threshold counters.
    mock_db.query.return_value = []
    # Phase 4c: rejection-reason rollup helper. Default empty rollups so the
    # template renders the "No rejections yet" empty state.
    mock_db.get_rejection_reason_rollup.return_value = []
    # Text-decision pattern analysis helpers. Default to "no run yet" so the
    # Patterns tab renders the empty state and the Summary card shows
    # "Last analysis: never".
    mock_db.get_last_text_analysis_run.return_value = None
    mock_db.is_text_analysis_running.return_value = (False, None)
    mock_db.get_text_decision_metric_summary.return_value = []
    mock_db.get_text_decision_phrase_findings.return_value = []


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
    _stub_analytics_helpers(mock_db)

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Metric Analytics" in body
    # Summary tab is now the default landing — sanity-check it rendered.
    assert "Image Relevance Classifier" in body
    assert "Recent Activity" in body
    assert 'id="summary-stats"' in body
    # Update Image Classifier button — Phase 3 button, disabled below threshold.
    assert "Update Image Classifier" in body
    # With 0 decisions and the default 100/10 threshold, the button is disabled
    # and surfaces a "need N more" helper.
    assert "more total decisions" in body
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
    _stub_analytics_helpers(mock_db)

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Decisions by Detection Tier" in body
    assert "Rejection Reasons by Detection Tier" in body
    # tier badge text rendered via |replace('_', ' ')|title
    assert "Tier 1 Cohort" in body
    assert "Tier 3 All" in body


def test_stats_summary_renders_recent_activity(client, mock_db):
    """Recent-activity rows render with the expected company / metric / reviewer cells."""
    from datetime import datetime

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

    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    mock_db.get_last_training_run.return_value = {
        "id": "abc",
        "model_type": "image_relevance",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_training_rows": 500,
        "num_positive_rows": 25,
        "model_path": "data/image_model/relevance_model.joblib",
        "report_path": None,
        "triggered_by": "RGM",
    }
    mock_db.count_image_decisions_since.return_value = {
        "total": 47,
        "positive": 6,
        "negative": 41,
    }
    mock_db.count_text_decisions_since.return_value = 12
    mock_db.get_recent_text_corrections.return_value = [
        {
            "created_at": ts,
            "reviewer_id": "RGM",
            "corrected_metric_id": "cm_total_customers",
            "corrected_value": None,
            "reviewer_notes": None,
            "fact_id": "fact-1",
            "original_metric_id": "cm_arpu",
            "original_value_raw": "100",
            "filing_id": 42,
            "company_name": "Acme",
            "cik": "0001",
        },
    ]
    mock_db.get_recent_text_additions.return_value = []
    mock_db.get_recent_image_additions.return_value = [
        {
            "created_at": ts,
            "confirmation_id": "conf-1",
            "img_id": "img-1",
            "confirmed_metric_id": "cm_net_revenue_retention",
            "reviewer_id": "RGM",
            "filing_id": 42,
            "company_name": "Acme",
            "cik": "0001",
        },
    ]
    mock_db.get_recent_image_corrections.return_value = []
    # Text-decision pattern analysis helpers (no run yet → empty Patterns tab).
    mock_db.get_last_text_analysis_run.return_value = None
    mock_db.is_text_analysis_running.return_value = (False, None)
    mock_db.get_text_decision_metric_summary.return_value = []
    mock_db.get_text_decision_phrase_findings.return_value = []

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-05-01 14:30 UTC" in body
    assert "(by RGM)" in body
    assert "47" in body  # total decisions since
    assert "cm_arpu" in body and "cm_total_customers" in body
    assert "cm_net_revenue_retention" in body
    assert "Acme" in body


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
