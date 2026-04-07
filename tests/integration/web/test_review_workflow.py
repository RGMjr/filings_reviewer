"""
Integration tests for Flask review routes (D1).

Tests the complete review workflow with a real database.

NOTE: Tests for the filing list (/filings), review page (/review/<id>), and
filter UI were removed — those routes now 301-redirect to the V2 unified
interface (/v2/review/). V2 unified coverage lives in test_v2_review_workflow.py.

The tests retained here cover navigation helper routes (/review/<id>/next and
/review/<id>/candidate/<id>) which still contain logic in review.py.
"""

from decimal import Decimal

import pytest

from src.review.models import CandidateFeatures
from src.web.app import close_pool, create_app
from tests.integration.conftest import create_test_company_and_filing


@pytest.fixture
def app(test_db_url):
    """Create Flask app for integration testing."""
    app = create_app("testing")
    app.config["DATABASE_URL"] = test_db_url
    app.config["TESTING"] = True
    yield app
    close_pool(app)


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
    company_id, filing_id = create_test_company_and_filing(db)

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


def test_navigation_handles_completion(client, test_filing, db):
    """Test navigation redirects to filing list when all reviewed."""
    filing_id = test_filing["filing_id"]

    for candidate_id in test_filing["candidate_ids"]:
        db.update_candidate_status(candidate_id, "reviewed")

    response = client.get(f"/review/{filing_id}/next")
    assert response.status_code == 302
    assert "/filings" in response.location


def test_invalid_candidate_returns_404(client, test_filing):
    """Test redirect for non-existent candidate."""
    filing_id = test_filing["filing_id"]
    response = client.get(f"/review/{filing_id}/candidate/99999")
    assert response.status_code == 302
    assert "/filings" in response.location
