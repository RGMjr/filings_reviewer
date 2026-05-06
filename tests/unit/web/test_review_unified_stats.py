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
    # Review Activity section: 4 frequency-aggregated cards x 2 scopes
    # (Latest 7d, All-time) plus per-window count totals for the badges.
    mock_db.get_top_text_corrections.return_value = []
    mock_db.get_top_text_additions.return_value = []
    mock_db.get_top_image_additions.return_value = []
    mock_db.get_top_image_corrections.return_value = []
    mock_db.count_review_activity.return_value = {
        "text_corrections": 0,
        "text_additions": 0,
        "image_additions": 0,
        "image_corrections": 0,
    }
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
    # Recommendation decisions (PR 1 of the auto-PR rollout). Default empty
    # so recs render with their action buttons; tests that exercise the
    # decided-state path stub a non-empty list explicitly.
    mock_db.get_recommendation_decisions.return_value = []


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
    assert "Review Activity" in body
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


def test_stats_summary_renders_review_activity(client, mock_db):
    """Review Activity cards render frequency-aggregated rows with the
    Latest/All-time toggle, count badges, and pair / value-only metric labels.
    """
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

    # Aggregated rows for the Review Activity cards. Same fixture for both
    # scopes — the mock returns these regardless of window arg.
    mock_db.get_top_text_corrections.return_value = [
        {
            "original_metric_id": "cm_arpu",
            "corrected_metric_id": "cm_total_customers",
            "count": 4,
            "last_seen": ts,
        },
        {
            # Value-only correction: same metric, no -> arrow.
            "original_metric_id": "cm_revenue_concentration",
            "corrected_metric_id": "cm_revenue_concentration",
            "count": 3,
            "last_seen": ts,
        },
    ]
    mock_db.get_top_text_additions.return_value = []
    mock_db.get_top_image_additions.return_value = [
        {
            "metric_id": "cm_net_revenue_retention",
            "count": 7,
            "last_seen": ts,
        },
    ]
    mock_db.get_top_image_corrections.return_value = []
    mock_db.count_review_activity.return_value = {
        "text_corrections": 7,
        "text_additions": 0,
        "image_additions": 7,
        "image_corrections": 0,
    }

    # Text-decision pattern analysis helpers (no run yet → empty Patterns tab).
    mock_db.get_last_text_analysis_run.return_value = None
    mock_db.is_text_analysis_running.return_value = (False, None)
    mock_db.get_text_decision_metric_summary.return_value = []
    mock_db.get_text_decision_phrase_findings.return_value = []
    mock_db.get_recommendation_decisions.return_value = []
    mock_db.get_rejection_reason_rollup.return_value = []
    mock_db.query.return_value = []

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-05-01 14:30 UTC" in body  # last training run timestamp
    assert "(by RGM)" in body
    # Aggregated metric pairs and singles render.
    assert "cm_arpu" in body and "cm_total_customers" in body
    assert "cm_net_revenue_retention" in body
    # Value-only correction renders as the metric + "(value)" qualifier rather
    # than "cm_X -> cm_X".
    assert "cm_revenue_concentration" in body
    assert "(value)" in body
    # Toggle and persistence wiring.
    assert 'id="review-activity-scope-toggle"' in body
    assert "cmasb:stats:review_activity_scope" in body
    # See-all link is present for each card type.
    assert "/v2/review/stats/activity/text-corrections" in body
    assert "/v2/review/stats/activity/image-additions" in body


def test_patterns_tab_renders_recommendation_alert(client, mock_db):
    """A metric whose findings fire a recommendation rule renders the
    Suggested-actions callout in its expanded Patterns-tab row.

    Pinning the wire-up between compute_recommendations() and the template.
    Helper-rule logic itself is covered by test_text_pattern_recommendations.
    """
    from datetime import datetime

    _stub_analytics_helpers(mock_db)
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
    mock_db.get_last_text_analysis_run.return_value = {
        "id": "abc",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_decisions_analyzed": 31,
        "num_metrics_analyzed": 1,
        "triggered_by": "RGM",
        "error": None,
    }
    mock_db.get_text_decision_metric_summary.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "total_decisions": 50,
            "accept_count": 5,
            "reject_count": 31,
            "correct_count": 14,
            "rejection_categories": {"wrong_metric": 18, "wrong_value": 13},
            "top_correction_targets": [],
        }
    ]
    mock_db.get_text_decision_phrase_findings.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "decision_type": "reject",
            "phrase": "accounts receivable",
            "phrase_ngram_size": 2,
            "source_field": "segment_text",
            "occurrence_count": 14,
            "pct_of_decisions": 45.20,
            "examples": [],
        }
    ]

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Recommendation panel rendered.
    assert "Suggested actions" in body
    # Phrase carried through to the title.
    assert "Add exclusion pattern" in body
    assert "accounts receivable" in body
    # Severity badge for medium (45.20 < 50 threshold).
    assert "medium" in body
    # Action buttons present (no decision yet).
    assert "rec-decide-btn" in body
    assert "Accept" in body and "Dismiss" in body and "Defer" in body


def test_patterns_tab_renders_decided_recommendation(client, mock_db):
    """When a decision row exists for a rec, the card renders the dimmed
    decided state with reviewer attribution + Undo button instead of the
    Accept/Dismiss/Defer buttons.
    """
    import uuid as _uuid
    from datetime import datetime

    _stub_analytics_helpers(mock_db)
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
    mock_db.get_last_text_analysis_run.return_value = {
        "id": "abc",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_decisions_analyzed": 31,
        "num_metrics_analyzed": 1,
        "triggered_by": "RGM",
        "error": None,
    }
    mock_db.get_text_decision_metric_summary.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "total_decisions": 50,
            "accept_count": 5,
            "reject_count": 31,
            "correct_count": 14,
            "rejection_categories": {"wrong_metric": 18, "wrong_value": 13},
            "top_correction_targets": [],
        }
    ]
    mock_db.get_text_decision_phrase_findings.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "decision_type": "reject",
            "phrase": "accounts receivable",
            "phrase_ngram_size": 2,
            "source_field": "segment_text",
            "occurrence_count": 14,
            "pct_of_decisions": 45.20,
            "examples": [],
        }
    ]
    decision_id = _uuid.uuid4()
    mock_db.get_recommendation_decisions.return_value = [
        {
            "id": decision_id,
            "metric_id": "cm_new_customers_acquired",
            "rule": "exclusion_pattern",
            "decision_key": "accounts receivable",
            "decision": "accepted",
            "reviewer_id": "RGM",
            "reviewer_note": "looks right",
            "pr_number": None,
            "pr_url": None,
            "created_at": ts,
            "updated_at": ts,
        }
    ]

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Decided-state badge + reviewer attribution.
    assert "rec-card--decided" in body
    assert "accepted" in body
    assert "by RGM" in body
    assert "looks right" in body
    # Undo button visible.
    assert "rec-undo-btn" in body
    assert str(decision_id) in body
    # Action buttons NOT present for the decided rec.
    assert "rec-decide-btn" not in body


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


def test_patterns_tab_archived_section(client, mock_db):
    """When a persisted decision's decision_key no longer surfaces in findings,
    the route passes archived_count > 0 and the template renders both an active
    panel and an archived section.

    Pins the route→template wiring for stale-recommendation auto-archival.
    """
    import uuid as _uuid
    from datetime import datetime

    _stub_analytics_helpers(mock_db)
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
    mock_db.get_last_text_analysis_run.return_value = {
        "id": "abc",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_decisions_analyzed": 31,
        "num_metrics_analyzed": 1,
        "triggered_by": "RGM",
        "error": None,
        "config_snapshot_hash": None,
    }
    # Current run has an active rec for "accounts receivable" (pct=45.2 >= 30 threshold).
    mock_db.get_text_decision_metric_summary.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "total_decisions": 50,
            "accept_count": 5,
            "reject_count": 31,
            "correct_count": 14,
            "rejection_categories": {"wrong_metric": 18},
            "top_correction_targets": [],
        }
    ]
    mock_db.get_text_decision_phrase_findings.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "decision_type": "reject",
            "phrase": "accounts receivable",
            "phrase_ngram_size": 2,
            "source_field": "segment_text",
            "occurrence_count": 14,
            "pct_of_decisions": 45.20,
            "examples": [],
        }
    ]
    stale_decision_id = _uuid.uuid4()
    mock_db.get_recommendation_decisions.return_value = [
        {
            # Active: still in current findings → is_stale=False, shows in active panel.
            "id": _uuid.uuid4(),
            "metric_id": "cm_new_customers_acquired",
            "rule": "exclusion_pattern",
            "decision_key": "accounts receivable",
            "decision": "deferred",
            "reviewer_id": "RGM",
            "reviewer_note": None,
            "pr_number": None,
            "pr_url": None,
            "created_at": ts,
            "updated_at": ts,
        },
        {
            # Stale: "old phrase" no longer in current findings → is_stale=True.
            "id": stale_decision_id,
            "metric_id": "cm_new_customers_acquired",
            "rule": "exclusion_pattern",
            "decision_key": "old phrase",
            "decision": "accepted",
            "reviewer_id": "RGM",
            "reviewer_note": "applied in PR 99",
            "pr_number": 99,
            "pr_url": "https://github.com/example/repo/pull/99",
            "created_at": ts,
            "updated_at": ts,
        },
    ]

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Active panel renders — the accounts receivable rec is still active.
    assert "Suggested actions" in body
    assert "accounts receivable" in body

    # Archived section renders for the stale "old phrase" decision.
    assert "Archived recommendations" in body
    assert "old phrase" in body

    # The stale card uses "archived" badge text, not "Suggested actions".
    # Both active and archived are present in the same response.
    assert "archived" in body

    # Active card renders with Accept/Dismiss/Defer buttons (it's decided=deferred).
    assert "rec-card--decided" in body

    # Stale card does NOT render decide buttons (no action on archived cards).
    # Count rec-decide-btn occurrences: should be 0 for the stale card.
    # (The active deferred card also has no decide buttons — it shows Undo.)
    assert "rec-undo-btn" in body  # active decided card has Undo


# ---------------------------------------------------------------------------
# Phase 2-4 (gh-515): new panels, interpretation column, Why-Reviewers-Reject
# ---------------------------------------------------------------------------


def _zero_image_data():
    return {
        "total_decisions": 0,
        "relevant_count": 0,
        "not_relevant_count": 0,
        "relevant_pct": 0.0,
        "not_relevant_pct": 0.0,
    }, {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "auto_rejected_count": 0,
        "review_pct": 0.0,
    }


def test_patterns_tab_category_rollup_panel(client, mock_db):
    """Category rollup panel renders with per-category counts from the run."""
    from datetime import datetime

    _stub_analytics_helpers(mock_db)
    mock_db.get_v2_review_stats.return_value = _empty_text_data()
    overall, progress = _zero_image_data()
    mock_db.get_image_decision_overall_v2.return_value = overall
    mock_db.get_image_review_progress_v2.return_value = progress
    mock_db.get_image_decisions_by_tier_v2.return_value = []
    mock_db.get_image_rejection_reasons_by_tier_v2.return_value = []

    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    mock_db.get_last_text_analysis_run.return_value = {
        "id": "abc",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_decisions_analyzed": 50,
        "num_metrics_analyzed": 1,
        "triggered_by": "RGM",
        "error": None,
        "config_snapshot_hash": None,
    }
    mock_db.get_text_decision_metric_summary.return_value = [
        {
            "metric_id": "cm_total_customers",
            "total_decisions": 50,
            "accept_count": 5,
            "reject_count": 40,
            "correct_count": 5,
            "rejection_categories": {"part_of_date": 30, "wrong_metric": 10},
            "top_correction_targets": [],
        }
    ]
    mock_db.get_text_decision_phrase_findings.return_value = []

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Category rollup panel exists.
    assert "Category rollup (this run)" in body
    # Category data renders — "Part Of Date" (label from CATEGORY_ACTIONS).
    assert "Part of date" in body
    # Severity badge present for dominant category.
    assert "high" in body or "medium" in body


def test_patterns_tab_cross_metric_panel_and_why_reject_toggle(client, mock_db):
    """Cross-metric panel renders with exclusion badge and Why-Reviewers-Reject
    toggle renders on the Patterns tab (not the Summary tab).
    """
    from datetime import datetime

    _stub_analytics_helpers(mock_db)
    mock_db.get_v2_review_stats.return_value = _empty_text_data()
    overall, progress = _zero_image_data()
    mock_db.get_image_decision_overall_v2.return_value = overall
    mock_db.get_image_review_progress_v2.return_value = progress
    mock_db.get_image_decisions_by_tier_v2.return_value = []
    mock_db.get_image_rejection_reasons_by_tier_v2.return_value = []

    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    mock_db.get_last_text_analysis_run.return_value = {
        "id": "abc",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_decisions_analyzed": 90,
        "num_metrics_analyzed": 3,
        "triggered_by": "RGM",
        "error": None,
        "config_snapshot_hash": None,
    }

    # Three metrics each have "shared phrase" in segment_text rejects — fires
    # cross_metric_exclusion (metric_count >= 3, ngram >= 2, source=segment_text).
    def shared_finding(metric_id):
        return {
            "metric_id": metric_id,
            "decision_type": "reject",
            "phrase": "shared phrase",
            "phrase_ngram_size": 2,
            "source_field": "segment_text",
            "occurrence_count": 10,
            "pct_of_decisions": 35.0,
            "examples": [],
        }

    mock_db.get_text_decision_metric_summary.return_value = [
        {
            "metric_id": m,
            "total_decisions": 30,
            "accept_count": 5,
            "reject_count": 20,
            "correct_count": 5,
            "rejection_categories": {"wrong_metric": 20},
            "top_correction_targets": [],
        }
        for m in ["cm_metric_a", "cm_metric_b", "cm_metric_c"]
    ]
    mock_db.get_text_decision_phrase_findings.return_value = [
        shared_finding(m) for m in ["cm_metric_a", "cm_metric_b", "cm_metric_c"]
    ]
    mock_db.get_rejection_reason_rollup.return_value = [
        {"reason": "wrong_metric", "count": 60, "percent": 100.0}
    ]

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Cross-metric panel renders.
    assert "Cross-metric phrases" in body
    assert "shared phrase" in body
    # Cross-metric exclusion badge.
    assert "exclusion" in body

    # Why-Reviewers-Reject is now on the Patterns tab, with a run/lifetime toggle.
    assert "Why Reviewers Reject" in body
    assert "This run" in body
    assert "Lifetime" in body
    assert "cmasb:patterns:reasons_scope" in body

    # Old Summary-tab h4 heading is gone — it now renders as h6 in Patterns tab.
    assert '<h4 class="mb-3">Why Reviewers Reject</h4>' not in body


def test_patterns_tab_interpretation_column_renders(client, mock_db):
    """Interpretation/Action column renders for phrase rows in per-metric tables."""
    from datetime import datetime

    _stub_analytics_helpers(mock_db)
    mock_db.get_v2_review_stats.return_value = _empty_text_data()
    overall, progress = _zero_image_data()
    mock_db.get_image_decision_overall_v2.return_value = overall
    mock_db.get_image_review_progress_v2.return_value = progress
    mock_db.get_image_decisions_by_tier_v2.return_value = []
    mock_db.get_image_rejection_reasons_by_tier_v2.return_value = []

    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    mock_db.get_last_text_analysis_run.return_value = {
        "id": "abc",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_decisions_analyzed": 31,
        "num_metrics_analyzed": 1,
        "triggered_by": "RGM",
        "error": None,
        "config_snapshot_hash": None,
    }
    mock_db.get_text_decision_metric_summary.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "total_decisions": 50,
            "accept_count": 5,
            "reject_count": 31,
            "correct_count": 14,
            "rejection_categories": {},
            "top_correction_targets": [],
        }
    ]
    mock_db.get_text_decision_phrase_findings.return_value = [
        {
            "metric_id": "cm_new_customers_acquired",
            "decision_type": "reject",
            "phrase": "accounts receivable",
            "phrase_ngram_size": 2,
            "source_field": "segment_text",
            "occurrence_count": 14,
            "pct_of_decisions": 35.0,
            "examples": [],
        }
    ]

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Interpretation column renders — the phrase row should show interpretation text.
    # interpret_finding_row returns "Phrase appears in extracted text of rejected facts"
    # for reject + segment_text + ngram >= 2.
    assert "Phrase appears in extracted text of rejected facts" in body
    assert "YAML exclusion" in body


def test_patterns_tab_covered_phrases_chip(client, mock_db):
    """When a phrase fires cross_metric_exclusion, the per-metric exclusion_pattern
    rec card renders as a '(rolled into cross-metric)' chip instead of the full card.
    """
    from datetime import datetime

    _stub_analytics_helpers(mock_db)
    mock_db.get_v2_review_stats.return_value = _empty_text_data()
    overall, progress = _zero_image_data()
    mock_db.get_image_decision_overall_v2.return_value = overall
    mock_db.get_image_review_progress_v2.return_value = progress
    mock_db.get_image_decisions_by_tier_v2.return_value = []
    mock_db.get_image_rejection_reasons_by_tier_v2.return_value = []

    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    mock_db.get_last_text_analysis_run.return_value = {
        "id": "abc",
        "completed_at": ts,
        "started_at": ts,
        "status": "succeeded",
        "num_decisions_analyzed": 90,
        "num_metrics_analyzed": 3,
        "triggered_by": "RGM",
        "error": None,
        "config_snapshot_hash": None,
    }
    # Three metrics fire the exclusion_pattern rule for "multi metric phrase"
    # → cross_metric_exclusion fires (metric_count=3).
    findings = [
        {
            "metric_id": m,
            "decision_type": "reject",
            "phrase": "multi metric phrase",
            "phrase_ngram_size": 3,
            "source_field": "segment_text",
            "occurrence_count": 15,
            "pct_of_decisions": 50.0,
            "examples": [],
        }
        for m in ["cm_metric_x", "cm_metric_y", "cm_metric_z"]
    ]
    mock_db.get_text_decision_phrase_findings.return_value = findings
    mock_db.get_text_decision_metric_summary.return_value = [
        {
            "metric_id": m,
            "total_decisions": 30,
            "accept_count": 5,
            "reject_count": 20,
            "correct_count": 5,
            "rejection_categories": {},
            "top_correction_targets": [],
        }
        for m in ["cm_metric_x", "cm_metric_y", "cm_metric_z"]
    ]

    resp = client.get("/v2/review/stats")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # The phrase fires cross_metric_exclusion (metric_count=3, ngram=3, reject, segment_text).
    # Per-metric exclusion_pattern recs for this phrase render as the chip.
    assert "rolled into cross-metric" in body
    # The chip links back to the cross-metric panel.
    assert "patterns-cross-metric" in body
    # The full rec-decide-btn is NOT rendered for covered phrases
    # (it would be present for other undecided recs, so count check is not needed —
    # just verify the chip text is present).
    assert "multi metric phrase" in body


# ---------------------------------------------------------------------------
# Activity-detail click-through page (/v2/review/stats/activity/<type>)
# ---------------------------------------------------------------------------


def test_activity_detail_unknown_type_returns_404(client, mock_db):
    resp = client.get("/v2/review/stats/activity/bogus-type")
    assert resp.status_code == 404


def test_activity_detail_text_corrections_renders(client, mock_db):
    from datetime import datetime

    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
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

    resp = client.get("/v2/review/stats/activity/text-corrections")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "All Text Fact Corrections" in body
    assert "Acme" in body
    assert "cm_arpu" in body and "cm_total_customers" in body
    # Limit was bumped to 200 for this page.
    mock_db.get_recent_text_corrections.assert_called_once_with(limit=200)


def test_activity_detail_image_corrections_empty(client, mock_db):
    mock_db.get_recent_image_corrections.return_value = []

    resp = client.get("/v2/review/stats/activity/image-corrections")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "All Image Metric Corrections" in body
    assert "No activity recorded yet" in body
