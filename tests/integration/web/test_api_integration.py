"""
Integration tests for API routes (D2).

Tests the JSON API endpoints with real database operations.
Verifies transaction atomicity and data integrity.
"""

import json
import os

import pytest

from src.infra.db import DatabaseAdapter
from src.web.app import create_app


@pytest.fixture(scope="module")
def db_url():
    """Get test database URL from environment."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="module")
def db_adapter(db_url):
    """Create database adapter for test setup/teardown."""
    return DatabaseAdapter(db_url)


@pytest.fixture
def app(db_url):
    """Create Flask test app with real database."""
    app = create_app(
        config_name="testing",
        config_override={
            "DATABASE_URL": db_url,
        },
    )
    return app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def test_data(db_adapter):
    """
    Create test data and return IDs.

    Returns:
        Tuple of (filing_id, candidate_id_1, candidate_id_2)
    """
    # Create company
    company_id = db_adapter.upsert_company(
        cik="0001234567",
        company_name="Test Company Inc.",
        ticker="TEST",
        industry_code="7370",
    )

    # Create filing
    filing_id = db_adapter.upsert_filing(
        company_id=company_id,
        cik="0001234567",
        accession_number="0001234567-23-000001",
        filing_date="2023-06-15",
        form_type="S-1",
        sec_html_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456723000001/filing.htm",
        is_in_scope_phase1=True,
        is_first_time_issuer=True,
        is_spac=False,
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )

    # Create two review candidates
    candidate_id_1 = db_adapter.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=150,
        context_text="We have 100,000 active customers.",
        raw_number_text="100,000",
        triggering_keyword="customers",
        keyword_distance=15,
        keyword_position="after",
        parsed_value=100000,
        parsed_unit="count",
        suggested_metric_id="active_customers",
        suggestion_confidence=0.85,
        features={
            "keyword_distance": 15,
            "keyword_position": "after",
            "is_in_table": False,
        },
    )

    candidate_id_2 = db_adapter.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=300,
        context_text="Our ARR reached $50 million.",
        raw_number_text="$50 million",
        triggering_keyword="ARR",
        keyword_distance=10,
        keyword_position="after",
        parsed_value=50000000,
        parsed_unit="usd",
        suggested_metric_id="arr",
        suggestion_confidence=0.90,
        features={
            "keyword_distance": 10,
            "keyword_position": "after",
            "is_in_table": False,
        },
    )

    yield filing_id, candidate_id_1, candidate_id_2

    # Cleanup - delete in correct order (child to parent)
    # Ignore errors if records are already deleted
    try:
        db_adapter.execute(
            "DELETE FROM review_decisions WHERE candidate_id IN (%(c1)s, %(c2)s)",
            {"c1": candidate_id_1, "c2": candidate_id_2},
        )
        db_adapter.execute(
            "DELETE FROM review_candidates WHERE candidate_id IN (%(c1)s, %(c2)s)",
            {"c1": candidate_id_1, "c2": candidate_id_2},
        )
        db_adapter.execute(
            "DELETE FROM filings WHERE filing_id = %(filing_id)s",
            {"filing_id": filing_id},
        )
        # Don't delete company since it may be shared across tests
    except Exception:
        # Cleanup errors are not critical - tests may have failed before creating records
        pass


# =============================================================================
# Integration Tests
# =============================================================================


class TestCreateDecisionIntegration:
    """Integration tests for POST /api/decisions with real database."""

    def test_accept_decision_end_to_end(self, client, db_adapter, test_data):
        """Test full accept decision flow with database."""
        filing_id, candidate_id_1, candidate_id_2 = test_data

        # Create accept decision
        response = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "accept",
                "assigned_metric_id": "active_customers",
                "reviewer_notes": "Looks correct",
                "review_time_seconds": 30,
            },
        )

        # Verify response
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert "decision_id" in data
        decision_id = data["decision_id"]

        # Verify next candidate is returned
        assert data["next_candidate"]["candidate_id"] == candidate_id_2

        # Verify decision in database
        decision = db_adapter.get_decision_for_candidate(candidate_id_1)
        assert decision is not None
        assert decision["decision_id"] == decision_id
        assert decision["decision"] == "accept"
        assert decision["assigned_metric_id"] == "active_customers"
        assert decision["reviewer_notes"] == "Looks correct"
        assert decision["review_time_seconds"] == 30

        # Verify candidate status updated
        candidate = db_adapter.get_review_candidate(candidate_id_1)
        assert candidate["review_status"] == "reviewed"

    def test_reject_decision_end_to_end(self, client, db_adapter, test_data):
        """Test full reject decision flow with database."""
        filing_id, candidate_id_1, candidate_id_2 = test_data

        # Create reject decision
        response = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "reject",
                "rejection_category": "wrong_metric",
                "rejection_reason": "This is total customers, not active",
            },
        )

        # Verify response
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"

        # Verify decision in database
        decision = db_adapter.get_decision_for_candidate(candidate_id_1)
        assert decision["decision"] == "reject"
        assert decision["rejection_category"] == "wrong_metric"
        assert decision["rejection_reason"] == "This is total customers, not active"
        assert decision["assigned_metric_id"] is None

        # Verify candidate status updated
        candidate = db_adapter.get_review_candidate(candidate_id_1)
        assert candidate["review_status"] == "reviewed"

    def test_reclassify_decision_end_to_end(self, client, db_adapter, test_data):
        """Test full reclassify decision flow with database."""
        filing_id, candidate_id_1, candidate_id_2 = test_data

        # Create reclassify decision
        response = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "reclassify",
                "assigned_metric_id": "total_customers",
                "reviewer_notes": "Should be total, not active",
            },
        )

        # Verify response
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"

        # Verify decision in database
        decision = db_adapter.get_decision_for_candidate(candidate_id_1)
        assert decision["decision"] == "reclassify"
        assert decision["assigned_metric_id"] == "total_customers"
        assert decision["reviewer_notes"] == "Should be total, not active"

    def test_transaction_atomicity(self, client, db_adapter, test_data):
        """Test that decision and status update happen atomically."""
        filing_id, candidate_id_1, candidate_id_2 = test_data

        # Verify candidate is pending
        candidate = db_adapter.get_review_candidate(candidate_id_1)
        assert candidate["review_status"] == "pending"

        # Create decision
        response = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "accept",
                "assigned_metric_id": "active_customers",
            },
        )

        assert response.status_code == 201

        # Verify both decision and status were updated
        decision = db_adapter.get_decision_for_candidate(candidate_id_1)
        candidate = db_adapter.get_review_candidate(candidate_id_1)
        assert decision is not None
        assert candidate["review_status"] == "reviewed"

    def test_duplicate_decision_prevented(self, client, db_adapter, test_data):
        """Test that duplicate decisions return 409 conflict."""
        filing_id, candidate_id_1, candidate_id_2 = test_data

        # Create first decision
        response1 = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "accept",
                "assigned_metric_id": "active_customers",
            },
        )
        assert response1.status_code == 201

        # Try to create second decision for same candidate
        response2 = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "reject",
                "rejection_category": "wrong_metric",
            },
        )

        # Verify 409 conflict
        assert response2.status_code == 409
        data = json.loads(response2.data)
        assert data["status"] == "error"
        assert "already has a decision" in data["message"]
        assert "existing_decision_id" in data

    def test_next_candidate_navigation(self, client, db_adapter, test_data):
        """Test next candidate navigation across multiple decisions."""
        filing_id, candidate_id_1, candidate_id_2 = test_data

        # Create decision for first candidate
        response1 = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "accept",
                "assigned_metric_id": "active_customers",
            },
        )

        # Verify next candidate is candidate_id_2
        data1 = json.loads(response1.data)
        assert data1["next_candidate"]["candidate_id"] == candidate_id_2

        # Create decision for second candidate
        response2 = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_2,
                "decision": "accept",
                "assigned_metric_id": "arr",
            },
        )

        # Verify no next candidate (all reviewed)
        data2 = json.loads(response2.data)
        assert data2["next_candidate"] is None

    def test_invalid_metric_id_database_check(self, client, db_adapter, test_data):
        """Test that invalid metric_id is caught by database foreign key constraint."""
        filing_id, candidate_id_1, candidate_id_2 = test_data

        # Try to create decision with clearly non-existent metric (using invalid format)
        response = client.post(
            "/api/decisions",
            json={
                "candidate_id": candidate_id_1,
                "decision": "accept",
                "assigned_metric_id": "this_metric_does_not_exist_in_database_12345",
            },
        )

        # Verify 500 error (foreign key constraint violation)
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"

        # Verify no decision was created (transaction rolled back)
        decision = db_adapter.get_decision_for_candidate(candidate_id_1)
        assert decision is None

        # Verify candidate status unchanged (transaction rolled back)
        candidate = db_adapter.get_review_candidate(candidate_id_1)
        assert candidate["review_status"] == "pending"
