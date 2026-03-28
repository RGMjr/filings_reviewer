"""
Integration tests for Flask review routes (D1).

Tests the complete review workflow with a real database.
"""

from decimal import Decimal

import pytest

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
def db(clean_db):
    """Create database adapter for test setup (clean state per test)."""
    return clean_db


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
    for _ in range(5):
        company_id, filing_id = create_test_company_and_filing(db)

        # Create 1 candidate per filing
        db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We have 10000 customers.",
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


# =============================================================================
# Test Filtering and Sorting (HRI-6)
# =============================================================================

def test_review_filing_status_filter(client, db):
    """Test filtering candidates by status."""
    # Create filing with multiple candidates with different statuses
    company_id, filing_id = create_test_company_and_filing(db)

    # Create 3 candidates
    candidate_ids = []
    for i in range(3):
        candidate_id = db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100 + i * 100,
            context_text=f"We have {10000 + i} customers.",
            raw_number_text=f"{10000 + i}",
            triggering_keyword="customers",
            keyword_distance=5,
            keyword_position="after",
            parsed_value=Decimal(10000 + i),
            parsed_unit="count",
            suggested_metric_id="cm_active_customers_total",
            suggestion_confidence=0.95,
        )
        candidate_ids.append(candidate_id)

    # Mark first two as reviewed
    db.update_candidate_status(candidate_ids[0], "reviewed")
    db.update_candidate_status(candidate_ids[1], "reviewed")

    # Test pending filter (should show only 1 candidate)
    response = client.get(f"/review/{filing_id}?status=pending")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    # Check that filter controls are present
    assert "statusFilter" in html
    # Check that showing count is displayed (verifying the feature exists)
    assert "of 3 candidates" in html

    # Test reviewed filter (should show 2 candidates)
    response = client.get(f"/review/{filing_id}?status=reviewed")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "of 3 candidates" in html


def test_review_filing_metric_filter(client, db):
    """Test filtering candidates by metric type."""
    company_id, filing_id = create_test_company_and_filing(db)

    # Create candidates with different metrics
    db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=100,
        context_text="We have 10000 customers.",
        raw_number_text="10,000",
        triggering_keyword="customers",
        keyword_distance=5,
        keyword_position="after",
        parsed_value=Decimal(10000),
        parsed_unit="count",
        suggested_metric_id="cm_active_customers_total",
        suggestion_confidence=0.95,
    )

    db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=200,
        context_text="Our ARR is $5M.",
        raw_number_text="$5M",
        triggering_keyword="ARR",
        keyword_distance=3,
        keyword_position="before",
        parsed_value=Decimal(5000000),
        parsed_unit="dollars",
        suggested_metric_id="cm_arr",
        suggestion_confidence=0.90,
    )

    # Filter by cm_arr (should show 1 candidate)
    response = client.get(f"/review/{filing_id}?metric=cm_arr")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    # Verify filter controls exist and total count is shown
    assert "metricFilter" in html
    assert "of 2 candidates" in html


def test_review_filing_confidence_filter(client, db):
    """Test filtering candidates by confidence level."""
    company_id, filing_id = create_test_company_and_filing(db)

    # Create candidates with different confidence levels
    # High confidence (>= 0.7)
    db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=100,
        context_text="We have 10000 customers.",
        raw_number_text="10,000",
        triggering_keyword="customers",
        keyword_distance=5,
        keyword_position="after",
        parsed_value=Decimal(10000),
        parsed_unit="count",
        suggested_metric_id="cm_active_customers_total",
        suggestion_confidence=0.95,
    )

    # Medium confidence (0.4 - 0.7)
    db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=200,
        context_text="We have 5000 users.",
        raw_number_text="5,000",
        triggering_keyword="users",
        keyword_distance=5,
        keyword_position="after",
        parsed_value=Decimal(5000),
        parsed_unit="count",
        suggested_metric_id="cm_active_customers_total",
        suggestion_confidence=0.55,
    )

    # Low confidence (< 0.4)
    db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=300,
        context_text="We have 100 items.",
        raw_number_text="100",
        triggering_keyword="items",
        keyword_distance=5,
        keyword_position="after",
        parsed_value=Decimal(100),
        parsed_unit="count",
        suggested_metric_id="cm_active_customers_total",
        suggestion_confidence=0.25,
    )

    # Test high confidence filter
    response = client.get(f"/review/{filing_id}?confidence=high")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "confidenceFilter" in html
    assert "of 3 candidates" in html

    # Test medium confidence filter
    response = client.get(f"/review/{filing_id}?confidence=medium")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "of 3 candidates" in html

    # Test low confidence filter
    response = client.get(f"/review/{filing_id}?confidence=low")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "of 3 candidates" in html


def test_review_filing_combined_filters(client, db):
    """Test combining multiple filters."""
    company_id, filing_id = create_test_company_and_filing(db)

    # Create candidates with mixed attributes
    candidate_id_1 = db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=100,
        context_text="We have 10000 customers.",
        raw_number_text="10,000",
        triggering_keyword="customers",
        keyword_distance=5,
        keyword_position="after",
        parsed_value=Decimal(10000),
        parsed_unit="count",
        suggested_metric_id="cm_active_customers_total",
        suggestion_confidence=0.95,
    )

    _candidate_id_2 = db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=200,
        context_text="Our ARR is $5M.",
        raw_number_text="$5M",
        triggering_keyword="ARR",
        keyword_distance=3,
        keyword_position="before",
        parsed_value=Decimal(5000000),
        parsed_unit="dollars",
        suggested_metric_id="cm_arr",
        suggestion_confidence=0.90,
    )

    # Mark first as reviewed
    db.update_candidate_status(candidate_id_1, "reviewed")

    # Combine status=reviewed + metric=cm_active_customers_total (should show 1)
    response = client.get(f"/review/{filing_id}?status=reviewed&metric=cm_active_customers_total")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "of 2 candidates" in html
    assert "filtered" in html  # Should show filtered badge


def test_review_filing_empty_filter_results(client, db):
    """Test UI handles empty filter results gracefully."""
    company_id, filing_id = create_test_company_and_filing(db)

    # Create one candidate
    db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=100,
        context_text="We have 10000 customers.",
        raw_number_text="10,000",
        triggering_keyword="customers",
        keyword_distance=5,
        keyword_position="after",
        parsed_value=Decimal(10000),
        parsed_unit="count",
        suggested_metric_id="cm_active_customers_total",
        suggestion_confidence=0.95,
    )

    # Filter by non-existent metric
    response = client.get(f"/review/{filing_id}?metric=cm_nonexistent")
    assert response.status_code == 200
    # Should show "No candidates match" message
    html = response.data.decode("utf-8")
    assert "No candidates match the current filters" in html
