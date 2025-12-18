"""
Integration tests for undo decision workflow (HRI-7).

Tests the complete undo workflow with a real database:
1. Create a decision
2. Undo it via DELETE /api/decisions/<decision_id>
3. Verify candidate returns to pending status
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.infra.db import DatabaseAdapter
from src.review.models import CandidateFeatures
from src.web.app import create_app
from tests.integration.conftest import create_test_company_and_filing


@pytest.fixture
def app(test_db_url):
    """Create Flask app for integration testing."""
    app = create_app("testing")
    app.config["DATABASE_URL"] = test_db_url
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def db(test_db_url):
    """Create database adapter for test setup."""
    return DatabaseAdapter(test_db_url)


@pytest.fixture
def test_candidate(db):
    """Create a test candidate for undo testing."""
    # Create company and filing
    company_id, filing_id = create_test_company_and_filing(db)

    # Create candidate
    features = CandidateFeatures(
        keyword_distance=5,
        keyword_position="after",
        is_in_table=False,
        is_in_risk_factors=False,
        contains_definition_language=True,
        has_period_mention=True,
        number_format="integer",
        value_magnitude=4.0,
        surrounding_numbers_count=0,
    )

    candidate_id = db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=100,
        context_text="We have 10,000 active customers.",
        raw_number_text="10,000",
        triggering_keyword="active customers",
        keyword_distance=5,
        keyword_position="after",
        parsed_value=Decimal(10000),
        parsed_unit="count",
        suggested_metric_id="cm_active_customers_total",
        suggestion_confidence=0.95,
        features=features.to_dict(),
    )

    return {
        "company_id": company_id,
        "filing_id": filing_id,
        "candidate_id": candidate_id,
    }


# =============================================================================
# Full Undo Workflow Tests
# =============================================================================


def test_full_undo_workflow(client, db, test_candidate):
    """Test complete undo workflow: create decision, undo, verify candidate is pending."""
    candidate_id = test_candidate["candidate_id"]
    filing_id = test_candidate["filing_id"]

    # Step 1: Create a decision (accept)
    decision_response = client.post(
        "/api/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "accept",
            "assigned_metric_id": "cm_active_customers_total",
            "review_time_seconds": 30,
        },
        content_type="application/json",
    )

    assert decision_response.status_code == 201
    decision_data = decision_response.get_json()
    decision_id = decision_data["decision_id"]

    # Verify candidate is marked as reviewed
    candidate = db.get_review_candidate(candidate_id)
    assert candidate["review_status"] == "reviewed"

    # Step 2: Undo the decision
    undo_response = client.delete(f"/api/decisions/{decision_id}")

    assert undo_response.status_code == 200
    undo_data = undo_response.get_json()
    assert undo_data["status"] == "success"
    assert undo_data["message"] == "Decision reverted"
    assert undo_data["candidate_id"] == candidate_id
    assert undo_data["candidate_url"] == f"/review/{filing_id}/candidate/{candidate_id}"

    # Step 3: Verify candidate is back to pending
    candidate_after = db.get_review_candidate(candidate_id)
    assert candidate_after["review_status"] == "pending"

    # Step 4: Verify decision no longer exists
    decision = db.get_decision_by_id(decision_id)
    assert decision is None


def test_undo_reject_decision(client, db, test_candidate):
    """Test undo works for reject decisions."""
    candidate_id = test_candidate["candidate_id"]

    # Create a reject decision
    decision_response = client.post(
        "/api/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "reject",
            "rejection_category": "not_a_metric",
            "rejection_reason": "This is a date, not a metric",
            "review_time_seconds": 15,
        },
        content_type="application/json",
    )

    assert decision_response.status_code == 201
    decision_id = decision_response.get_json()["decision_id"]

    # Undo the decision
    undo_response = client.delete(f"/api/decisions/{decision_id}")
    assert undo_response.status_code == 200

    # Verify candidate is pending
    candidate = db.get_review_candidate(candidate_id)
    assert candidate["review_status"] == "pending"


def test_undo_reclassify_decision(client, db, test_candidate):
    """Test undo works for reclassify decisions."""
    candidate_id = test_candidate["candidate_id"]

    # Create a reclassify decision
    decision_response = client.post(
        "/api/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "reclassify",
            "assigned_metric_id": "cm_monthly_active_users",
            "review_time_seconds": 20,
        },
        content_type="application/json",
    )

    assert decision_response.status_code == 201
    decision_id = decision_response.get_json()["decision_id"]

    # Undo the decision
    undo_response = client.delete(f"/api/decisions/{decision_id}")
    assert undo_response.status_code == 200

    # Verify candidate is pending
    candidate = db.get_review_candidate(candidate_id)
    assert candidate["review_status"] == "pending"


def test_undo_nonexistent_decision(client, db):
    """Test undoing a nonexistent decision returns 404."""
    undo_response = client.delete("/api/decisions/99999")

    assert undo_response.status_code == 404
    data = undo_response.get_json()
    assert data["status"] == "error"
    assert data["message"] == "Decision not found"


def test_undo_already_undone_decision(client, db, test_candidate):
    """Test undoing an already-undone decision returns 404."""
    candidate_id = test_candidate["candidate_id"]

    # Create a decision
    decision_response = client.post(
        "/api/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "accept",
            "assigned_metric_id": "cm_active_customers_total",
            "review_time_seconds": 25,
        },
        content_type="application/json",
    )
    decision_id = decision_response.get_json()["decision_id"]

    # Undo once (should succeed)
    first_undo = client.delete(f"/api/decisions/{decision_id}")
    assert first_undo.status_code == 200

    # Try to undo again (should fail with 404)
    second_undo = client.delete(f"/api/decisions/{decision_id}")
    assert second_undo.status_code == 404
    data = second_undo.get_json()
    assert data["message"] == "Decision not found"


def test_undo_with_reviewer_notes(client, db, test_candidate):
    """Test undo works when decision has reviewer notes."""
    candidate_id = test_candidate["candidate_id"]

    # Create decision with notes
    decision_response = client.post(
        "/api/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "accept",
            "assigned_metric_id": "cm_active_customers_total",
            "reviewer_notes": "Clear metric with good context",
            "review_time_seconds": 35,
        },
        content_type="application/json",
    )
    decision_id = decision_response.get_json()["decision_id"]

    # Undo should still work
    undo_response = client.delete(f"/api/decisions/{decision_id}")
    assert undo_response.status_code == 200

    # Verify candidate is pending
    candidate = db.get_review_candidate(candidate_id)
    assert candidate["review_status"] == "pending"


def test_candidate_can_be_reviewed_again_after_undo(client, db, test_candidate):
    """Test that after undo, candidate can receive a new decision."""
    candidate_id = test_candidate["candidate_id"]

    # Create original decision
    first_decision = client.post(
        "/api/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "accept",
            "assigned_metric_id": "cm_active_customers_total",
            "review_time_seconds": 20,
        },
        content_type="application/json",
    )
    first_decision_id = first_decision.get_json()["decision_id"]

    # Undo it
    client.delete(f"/api/decisions/{first_decision_id}")

    # Create new decision
    second_decision = client.post(
        "/api/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "reject",
            "rejection_category": "duplicate",
            "review_time_seconds": 15,
        },
        content_type="application/json",
    )

    assert second_decision.status_code == 201
    assert second_decision.get_json()["status"] == "success"

    # Verify candidate is reviewed with new decision
    candidate = db.get_review_candidate(candidate_id)
    assert candidate["review_status"] == "reviewed"

    decision = db.get_decision_for_candidate(candidate_id)
    assert decision["decision"] == "reject"
    assert decision["rejection_category"] == "duplicate"
