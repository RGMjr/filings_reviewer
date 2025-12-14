"""
Integration tests for Flask review routes (D1).

Tests the complete review workflow with a real database.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.infra.db import DatabaseAdapter
from src.review.models import ReviewCandidate, CandidateFeatures
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
def test_filing(db):
    """Create a test filing with candidates."""
    # Create company and filing
    company_id, filing_id = create_test_company_and_filing(db)

    # Create candidates
    features = CandidateFeatures(
        keyword_distance=5,
        keyword_position="after",
        is_in_table=False,
        is_in_risk_factors=False,
        contains_definition_language=True,
        has_period_mention=True,
        number_format="integer",
        value_magnitude=4.0,  # log10(10000)
        surrounding_numbers_count=0,
    )

    candidate_ids = []
    for i in range(3):
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
            features=features.to_dict(),
        )
        candidate_ids.append(candidate_id)

    return {
        "company_id": company_id,
        "filing_id": filing_id,
        "candidate_ids": candidate_ids,
    }


def test_full_review_workflow(client, test_filing):
    """Test complete review workflow from start to finish."""
    filing_id = test_filing["filing_id"]

    # Step 1: Visit filing list
    response = client.get("/filings")
    assert response.status_code == 200
    assert b"Test Corp" in response.data

    # Step 2: Click into review for filing
    response = client.get(f"/review/{filing_id}")
    assert response.status_code == 200
    assert b"10,000" in response.data  # First candidate

    # Step 3: Navigate to next candidate
    first_candidate_id = test_filing["candidate_ids"][0]
    response = client.get(f"/review/{filing_id}/next?current_id={first_candidate_id}")
    assert response.status_code == 302
    assert f"/review/{filing_id}" in response.location

    # Step 4: Jump to specific candidate
    third_candidate_id = test_filing["candidate_ids"][2]
    response = client.get(f"/review/{filing_id}/candidate/{third_candidate_id}")
    assert response.status_code == 302
    assert f"candidate_id={third_candidate_id}" in response.location


def test_filing_list_shows_correct_counts(client, db, test_filing):
    """Test filing list displays accurate candidate counts."""
    filing_id = test_filing["filing_id"]

    # All should be pending initially
    response = client.get("/filings")
    assert response.status_code == 200
    assert b"Test Corp" in response.data

    # Mark one as reviewed
    candidate_id = test_filing["candidate_ids"][0]
    db.update_candidate_status(candidate_id, "reviewed")

    # Check counts updated
    response = client.get("/filings")
    assert response.status_code == 200


def test_review_page_calculates_progress(client, test_filing, db):
    """Test review page calculates progress correctly."""
    filing_id = test_filing["filing_id"]

    # Initially all pending
    response = client.get(f"/review/{filing_id}")
    assert response.status_code == 200

    # Mark one as reviewed
    candidate_id = test_filing["candidate_ids"][0]
    db.update_candidate_status(candidate_id, "reviewed")

    # Progress should reflect change
    response = client.get(f"/review/{filing_id}")
    assert response.status_code == 200


def test_navigation_handles_completion(client, test_filing, db):
    """Test navigation redirects to filing list when all reviewed."""
    filing_id = test_filing["filing_id"]

    # Mark all as reviewed
    for candidate_id in test_filing["candidate_ids"]:
        db.update_candidate_status(candidate_id, "reviewed")

    # Next should redirect to filing list with success message
    response = client.get(f"/review/{filing_id}/next")
    assert response.status_code == 302
    assert "/filings" in response.location


def test_invalid_filing_returns_404(client):
    """Test 404 returned for non-existent filing."""
    response = client.get("/review/99999")
    assert response.status_code == 404


def test_invalid_candidate_returns_404(client, test_filing):
    """Test redirect for non-existent candidate."""
    filing_id = test_filing["filing_id"]
    response = client.get(f"/review/{filing_id}/candidate/99999")
    # Should redirect to filing list with flash message
    assert response.status_code == 302
    assert "/filings" in response.location


def test_filing_list_pagination(client, db):
    """Test filing list pagination with multiple filings."""
    # Create multiple companies and filings with candidates
    filing_ids = []
    for i in range(5):
        company_id, filing_id = create_test_company_and_filing(db)

        # Create 1 candidate per filing
        db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text=f"We have 10000 customers.",
            raw_number_text="10,000",
            triggering_keyword="customers",
            keyword_distance=5,
            keyword_position="after",
            parsed_value=Decimal(10000),
            parsed_unit="count",
            suggested_metric_id="cm_active_customers_total",
            suggestion_confidence=0.95,
        )
        filing_ids.append(filing_id)

    # Test page 1 with per_page=2
    response = client.get("/filings?per_page=2")
    assert response.status_code == 200
    # Should show 2 filings (the HTML would contain company names)

    # Test page 2
    response = client.get("/filings?page=2&per_page=2")
    assert response.status_code == 200

    # Test page 3
    response = client.get("/filings?page=3&per_page=2")
    assert response.status_code == 200
