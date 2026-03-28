"""
Integration tests for bulk decision workflow (HRI-8).

Tests the complete end-to-end bulk review workflow with a real database.
"""

from decimal import Decimal

import pytest

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
def db(clean_db):
    """Create database adapter for test setup (clean state per test)."""
    return clean_db


@pytest.fixture
def test_filing_with_candidates(db):
    """Create a test filing with multiple pending candidates."""
    company_id, filing_id = create_test_company_and_filing(db)

    candidate_ids = []
    for i in range(5):
        candidate_id = db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100 * (i + 1),
            context_text=f"We have {10000 * (i + 1)} active customers.",
            raw_number_text=f"{10000 * (i + 1):,}",
            triggering_keyword="active customers",
            keyword_distance=5,
            keyword_position="after",
            parsed_value=Decimal(10000 * (i + 1)),
            parsed_unit="count",
            suggested_metric_id="cm_active_customers_total",
            suggestion_confidence=0.95,
        )
        candidate_ids.append(candidate_id)

    return {
        "company_id": company_id,
        "filing_id": filing_id,
        "candidate_ids": candidate_ids,
    }


class TestBulkAcceptWorkflow:
    """Test complete bulk accept workflow."""

    def test_bulk_accept_all_pending(self, client, db, test_filing_with_candidates):
        """Bulk accept should mark all candidates as reviewed with correct metric."""
        filing = test_filing_with_candidates
        candidate_ids = filing["candidate_ids"]

        # Submit bulk accept
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_active_customers_total",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["processed_count"] == 5
        assert len(data["decision_ids"]) == 5
        assert data["failed_candidates"] == []

        # Verify all candidates are now reviewed
        for candidate_id in candidate_ids:
            candidate = db.get_review_candidate(candidate_id)
            assert candidate["review_status"] == "reviewed"

            decision = db.get_decision_for_candidate(candidate_id)
            assert decision is not None
            assert decision["decision"] == "accept"
            assert decision["assigned_metric_id"] == "cm_active_customers_total"

    def test_bulk_accept_subset_of_candidates(self, client, db, test_filing_with_candidates):
        """Bulk accept subset should only affect selected candidates."""
        filing = test_filing_with_candidates
        subset_ids = filing["candidate_ids"][:3]  # First 3 only

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": subset_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_active_customers_total",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["processed_count"] == 3

        # Verify first 3 are reviewed
        for candidate_id in subset_ids:
            candidate = db.get_review_candidate(candidate_id)
            assert candidate["review_status"] == "reviewed"

        # Verify last 2 are still pending
        for candidate_id in filing["candidate_ids"][3:]:
            candidate = db.get_review_candidate(candidate_id)
            assert candidate["review_status"] == "pending"


class TestBulkRejectWorkflow:
    """Test complete bulk reject workflow."""

    def test_bulk_reject_with_category(self, client, db, test_filing_with_candidates):
        """Bulk reject should mark all candidates as rejected with category."""
        filing = test_filing_with_candidates
        candidate_ids = filing["candidate_ids"]

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "reject",
                "rejection_category": "wrong_metric",
                "rejection_reason": "These are not customer counts",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["processed_count"] == 5

        # Verify all are rejected
        for candidate_id in candidate_ids:
            candidate = db.get_review_candidate(candidate_id)
            assert candidate["review_status"] == "reviewed"

            decision = db.get_decision_for_candidate(candidate_id)
            assert decision["decision"] == "reject"
            assert decision["rejection_category"] == "wrong_metric"
            assert decision["rejection_reason"] == "These are not customer counts"


class TestBulkEdgeCasesIntegration:
    """Test edge cases with real database."""

    def test_already_reviewed_candidates_skipped(self, client, db, test_filing_with_candidates):
        """Already reviewed candidates should be skipped with errors."""
        filing = test_filing_with_candidates
        candidate_ids = filing["candidate_ids"]

        # Review first candidate individually
        db.insert_review_decision(
            candidate_id=candidate_ids[0],
            decision="accept",
            assigned_metric_id="cm_active_customers_total",
        )

        # Try to bulk accept all (including already reviewed)
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_active_customers_total",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        # Should process 4 (skip the already reviewed one)
        assert data["processed_count"] == 4
        assert len(data["failed_candidates"]) == 1
        assert data["failed_candidates"][0]["candidate_id"] == candidate_ids[0]
        assert "Already reviewed" in data["failed_candidates"][0]["error"]

    def test_nonexistent_candidate_id_skipped(self, client, db, test_filing_with_candidates):
        """Nonexistent candidate IDs should be skipped."""
        filing = test_filing_with_candidates
        candidate_ids = filing["candidate_ids"] + [99999]  # Add nonexistent ID

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_active_customers_total",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["processed_count"] == 5  # Only existing ones processed
        assert len(data["failed_candidates"]) == 1
        assert data["failed_candidates"][0]["candidate_id"] == 99999

    def test_bulk_reject_all_categories(self, client, db, test_filing_with_candidates):
        """Test bulk reject with each rejection category."""
        filing = test_filing_with_candidates
        categories = [
            "wrong_metric",
            "not_a_metric",
            "wrong_value",
            "wrong_period",
            "duplicate",
        ]

        for i, category in enumerate(categories):
            response = client.post(
                "/api/bulk-decisions",
                json={
                    "candidate_ids": [filing["candidate_ids"][i]],
                    "decision": "reject",
                    "rejection_category": category,
                },
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["processed_count"] == 1

            decision = db.get_decision_for_candidate(filing["candidate_ids"][i])
            assert decision["rejection_category"] == category


class TestBulkSafetyLimits:
    """Test safety limits and constraints."""

    def test_exactly_20_candidates_succeeds(self, client, db):
        """Exactly 20 candidates should succeed."""
        company_id, filing_id = create_test_company_and_filing(db)

        # Create exactly 20 candidates
        candidate_ids = []
        for i in range(20):
            candidate_id = db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=100 * (i + 1),
                context_text=f"Test {i}",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
                parsed_value=Decimal(100),
                parsed_unit="count",
                suggested_metric_id="cm_active_customers_total",
                suggestion_confidence=0.95,
            )
            candidate_ids.append(candidate_id)

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_active_customers_total",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["processed_count"] == 20

    def test_51_candidates_returns_403(self, client, db):
        """51 candidates should return 403 (API limit is 50)."""
        company_id, filing_id = create_test_company_and_filing(db)

        # Create 51 candidates
        candidate_ids = []
        for i in range(51):
            candidate_id = db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=100 * (i + 1),
                context_text=f"Test {i}",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
                parsed_value=Decimal(100),
                parsed_unit="count",
                suggested_metric_id="cm_active_customers_total",
                suggestion_confidence=0.95,
            )
            candidate_ids.append(candidate_id)

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_active_customers_total",
            },
        )

        assert response.status_code == 403
        data = response.get_json()
        assert "Maximum 50 candidates" in data["message"]
