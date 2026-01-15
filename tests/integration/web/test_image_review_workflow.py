"""
Integration tests for Flask image review routes (IMG-1-8).

Tests the complete image review workflow from database to API to UI rendering.
"""

import pytest

from src.web.app import create_app
from tests.integration.conftest import (
    create_test_company_and_filing,
    create_test_image_candidate,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def app(test_db_url):
    """Create Flask app for integration testing."""
    app = create_app("testing")
    app.config["DATABASE_URL"] = test_db_url
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db(clean_db):
    """Use clean_db fixture that truncates tables between tests."""
    return clean_db


@pytest.fixture
def sample_filing(db):
    """Create a filing for testing."""
    company_id, filing_id = create_test_company_and_filing(db)
    return {"company_id": company_id, "filing_id": filing_id}


@pytest.fixture
def sample_image_candidates(db, sample_filing):
    """Create image candidates across all tiers."""
    filing_id = sample_filing["filing_id"]
    company_id = sample_filing["company_id"]
    candidate_ids = []

    # Tier 1: High confidence cohort (1 candidate)
    _, _, cid1 = create_test_image_candidate(
        db,
        filing_id=filing_id,
        company_id=company_id,
        image_src="cohort_chart.jpg",
        detection_tier="tier_1_cohort",
        cohort_confidence=0.95,
        image_index=1,
    )
    candidate_ids.append(cid1)

    # Tier 2: Large images (2 candidates)
    for i in range(2):
        _, _, cid = create_test_image_candidate(
            db,
            filing_id=filing_id,
            company_id=company_id,
            image_src=f"large_chart_{i}.jpg",
            detection_tier="tier_2_large",
            cohort_confidence=0.60,
            image_index=i + 2,
        )
        candidate_ids.append(cid)

    # Tier 3: All non-decorative (3 candidates)
    for i in range(3):
        _, _, cid = create_test_image_candidate(
            db,
            filing_id=filing_id,
            company_id=company_id,
            image_src=f"misc_chart_{i}.jpg",
            detection_tier="tier_3_all",
            cohort_confidence=0.40,
            image_index=i + 4,
        )
        candidate_ids.append(cid)

    return candidate_ids


# =============================================================================
# Filing List Page Tests (3 tests)
# =============================================================================


def test_filing_list_renders(client, sample_filing, sample_image_candidates):
    """Filing list page renders with image candidate counts."""
    response = client.get("/review/images/filings")
    assert response.status_code == 200
    # Company name should appear in HTML
    assert b"Test Corp" in response.data


def test_filing_list_shows_counts(client, sample_filing, sample_image_candidates):
    """Filing list shows correct pending/reviewed counts."""
    response = client.get("/review/images/filings")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    # Should show 6 total candidates (1 + 2 + 3 from fixture)
    assert "6" in html


def test_filing_list_pagination(client, sample_filing, sample_image_candidates):
    """Filing list pagination works."""
    response = client.get("/review/images/filings?page=1&per_page=5")
    assert response.status_code == 200


# =============================================================================
# Review Interface Tests (4 tests)
# =============================================================================


def test_review_page_renders(client, sample_filing, sample_image_candidates):
    """Review page renders with candidate data."""
    filing_id = sample_filing["filing_id"]
    response = client.get(f"/review/images/{filing_id}")
    assert response.status_code == 200
    # Should contain image URL or SEC reference
    html = response.data.decode("utf-8")
    assert "sec.gov" in html or "image" in html.lower()


def test_review_page_shows_specific_candidate(
    client, sample_filing, sample_image_candidates
):
    """Review page shows specific candidate when requested."""
    filing_id = sample_filing["filing_id"]
    candidate_id = sample_image_candidates[0]
    response = client.get(
        f"/review/images/{filing_id}?image_candidate_id={candidate_id}"
    )
    assert response.status_code == 200


def test_review_page_invalid_filing_returns_404(client):
    """Review page returns 404 for invalid filing."""
    response = client.get("/review/images/99999")
    assert response.status_code == 404


def test_review_page_shows_tier_info(client, sample_filing, sample_image_candidates):
    """Review page displays detection tier information."""
    filing_id = sample_filing["filing_id"]
    response = client.get(f"/review/images/{filing_id}")
    assert response.status_code == 200
    html = response.data.decode("utf-8").lower()
    assert "tier" in html


# =============================================================================
# API Decision Tests (5 tests)
# =============================================================================


def test_create_relevant_decision(client, sample_filing, sample_image_candidates):
    """API creates relevant decision with chart type."""
    candidate_id = sample_image_candidates[0]
    response = client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": candidate_id,
            "decision": "relevant",
            "chart_type": "bar_chart",
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "success"
    assert "decision_id" in data


def test_create_not_relevant_decision(client, sample_filing, sample_image_candidates):
    """API creates not_relevant decision with rejection reason."""
    candidate_id = sample_image_candidates[1]
    response = client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": candidate_id,
            "decision": "not_relevant",
            "rejection_reason": "decorative",
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "success"


def test_decision_returns_next_candidate(client, sample_filing, sample_image_candidates):
    """API returns next candidate info after decision."""
    candidate_id = sample_image_candidates[0]
    response = client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": candidate_id,
            "decision": "relevant",
            "chart_type": "line_chart",
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert "next_candidate" in data


def test_decision_validation_chart_type_required(
    client, sample_filing, sample_image_candidates
):
    """API rejects relevant decision without chart_type."""
    candidate_id = sample_image_candidates[2]  # Use unused candidate
    response = client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": candidate_id,
            "decision": "relevant",
            # Missing chart_type
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"


def test_decision_validation_rejection_reason_required(
    client, sample_filing, sample_image_candidates
):
    """API rejects not_relevant decision without rejection_reason."""
    candidate_id = sample_image_candidates[3]  # Use unused candidate
    response = client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": candidate_id,
            "decision": "not_relevant",
            # Missing rejection_reason
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"


# =============================================================================
# Skip and Undo Tests (3 tests)
# =============================================================================


def test_skip_candidate(client, sample_filing, sample_image_candidates):
    """API skips candidate and returns next."""
    candidate_id = sample_image_candidates[4]  # Use unused candidate
    response = client.post(f"/api/image-candidates/{candidate_id}/skip")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"


def test_undo_decision(client, sample_filing, sample_image_candidates):
    """API deletes decision and resets candidate status."""
    # First create a decision
    candidate_id = sample_image_candidates[5]  # Use unused candidate
    create_response = client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": candidate_id,
            "decision": "relevant",
            "chart_type": "cohort_table",
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    decision_id = create_response.get_json()["decision_id"]

    # Then delete it
    response = client.delete(f"/api/image-decisions/{decision_id}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"


def test_undo_invalid_decision_returns_404(client):
    """API returns 404 for invalid decision ID."""
    response = client.delete("/api/image-decisions/99999")
    assert response.status_code == 404


# =============================================================================
# End-to-End Workflow Test (1 test)
# =============================================================================


def test_full_review_workflow(client, db, sample_filing, sample_image_candidates):
    """Complete workflow: list → review → decide → navigate."""
    filing_id = sample_filing["filing_id"]

    # 1. View filing list
    list_response = client.get("/review/images/filings")
    assert list_response.status_code == 200

    # 2. Enter review for filing
    review_response = client.get(f"/review/images/{filing_id}")
    assert review_response.status_code == 200

    # 3. Make decision on first candidate
    decision_response = client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": sample_image_candidates[0],
            "decision": "relevant",
            "chart_type": "stacked_bar",
        },
        content_type="application/json",
    )
    assert decision_response.status_code == 201
    data = decision_response.get_json()
    assert data["next_candidate"] is not None  # More candidates remain
    next_url = data["next_candidate"]["url"]

    # 4. Follow to next candidate
    next_response = client.get(next_url)
    assert next_response.status_code == 200

    # 5. Verify database state - candidate should be reviewed
    candidate = db.get_image_review_candidate(sample_image_candidates[0])
    assert candidate["review_status"] == "reviewed"


# =============================================================================
# Pattern Learning Verification (1 test)
# =============================================================================


def test_tier_distribution_captured_with_decisions(
    client, db, sample_filing, sample_image_candidates
):
    """Verify detection_tier is preserved when decisions are made."""
    # Make decision on tier_1_cohort candidate
    client.post(
        "/api/image-decisions",
        json={
            "image_candidate_id": sample_image_candidates[0],
            "decision": "relevant",
            "chart_type": "cohort_table",
        },
        content_type="application/json",
    )

    # Verify tier is still accessible from candidate
    candidate = db.get_image_review_candidate(sample_image_candidates[0])
    assert candidate["detection_tier"] == "tier_1_cohort"


# =============================================================================
# Navigation Tests (2 tests)
# =============================================================================


def test_next_candidate_route(client, sample_filing, sample_image_candidates):
    """Next candidate route redirects correctly."""
    filing_id = sample_filing["filing_id"]
    response = client.get(f"/review/images/{filing_id}/next")
    assert response.status_code == 302  # Redirect to next pending


def test_next_candidate_with_current_id(client, sample_filing, sample_image_candidates):
    """Next candidate route respects current parameter."""
    filing_id = sample_filing["filing_id"]
    current_id = sample_image_candidates[0]
    response = client.get(f"/review/images/{filing_id}/next?current={current_id}")
    assert response.status_code == 302
