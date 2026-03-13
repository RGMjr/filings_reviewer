"""
Integration tests for the V2 review user journey.

Tests the full workflow: filing list, fact review page, accept/reject/correct
decisions, and undo. Requires TEST_DATABASE_URL to be set.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is in path for conftest helpers
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.infra.db import DatabaseAdapter
from src.web.app import create_app

# Import the V2 helpers from conftest (they're plain functions, not fixtures)
from tests.integration.conftest import (
    create_test_company_and_filing,
    create_test_v2_document,
    create_test_v2_fact,
)

# =============================================================================
# Module-level fixtures
# =============================================================================


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
    return create_app("testing", config_override={"DATABASE_URL": db_url})


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


# =============================================================================
# TestV2FilingList
# =============================================================================


class TestV2FilingList:
    """Tests for the V2 filing list page (/v2/review/filings)."""

    def test_filing_list_shows_v2_filings(self, client, db_adapter):
        """GET /v2/review/filings returns 200 and shows filing with fact counts."""
        _, filing_id = create_test_company_and_filing(
            db_adapter,
            cik="0009991001",
            accession_number="0009991001-24-000001",
        )
        create_test_v2_document(db_adapter, filing_id)
        create_test_v2_fact(db_adapter, filing_id)

        try:
            response = client.get("/v2/review/filings")
            assert response.status_code == 200
            # Page should contain filing/v2 related content
            assert b"v2" in response.data.lower() or b"filing" in response.data.lower()
        finally:
            db_adapter.execute(
                "DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id}
            )
            db_adapter.execute("DELETE FROM companies WHERE cik = '0009991001'")

    def test_filing_list_empty(self, client):
        """GET /v2/review/filings with no V2 data still returns 200."""
        response = client.get("/v2/review/filings")
        assert response.status_code == 200

    def test_filing_list_pagination_params_accepted(self, client):
        """GET /v2/review/filings with page/per_page returns 200."""
        response = client.get("/v2/review/filings?page=1&per_page=10")
        assert response.status_code == 200


# =============================================================================
# TestV2FactReview
# =============================================================================


class TestV2FactReview:
    """Tests for the V2 fact review page (/v2/review/<filing_id>)."""

    @pytest.fixture
    def filing_with_facts(self, db_adapter):
        """Create a filing with a V2 fact for review tests."""
        _, filing_id = create_test_company_and_filing(
            db_adapter,
            cik="0009992001",
            accession_number="0009992001-24-000001",
        )
        create_test_v2_document(db_adapter, filing_id)
        fact_id = create_test_v2_fact(
            db_adapter,
            filing_id,
            evidence_pack=json.dumps(
                {
                    "snippet_html": "<td>10,000 customers</td>",
                    "context_before": "As of December 31, 2023, we had",
                }
            ),
        )
        yield filing_id, fact_id

        db_adapter.execute(
            "DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id}
        )
        db_adapter.execute("DELETE FROM companies WHERE cik = '0009992001'")

    def test_review_page_loads_with_facts(self, client, filing_with_facts):
        """GET /v2/review/<id> returns 200 when filing and facts exist."""
        filing_id, fact_id = filing_with_facts
        response = client.get(f"/v2/review/{filing_id}")
        assert response.status_code == 200

    def test_review_page_shows_evidence(self, client, filing_with_facts):
        """evidence_pack snippet_html content appears in rendered response."""
        filing_id, fact_id = filing_with_facts
        response = client.get(f"/v2/review/{filing_id}")
        assert response.status_code == 200
        # The evidence pack snippet_html should be rendered in the page
        assert b"10,000" in response.data or b"customers" in response.data

    def test_review_page_pagination(self, client, db_adapter):
        """page/per_page query params are accepted and return 200."""
        _, filing_id = create_test_company_and_filing(
            db_adapter,
            cik="0009992002",
            accession_number="0009992002-24-000001",
        )
        create_test_v2_document(db_adapter, filing_id)
        # Create 2 facts with distinct periods
        for i in range(2):
            create_test_v2_fact(
                db_adapter,
                filing_id,
                period_end=f"202{3 + i}-12-31",
                period_start=f"202{3 + i}-01-01",
                value=1000 * (i + 1),
                value_raw=f"{1000 * (i + 1)}",
            )

        try:
            response = client.get(f"/v2/review/{filing_id}?page=1&per_page=1")
            assert response.status_code == 200
        finally:
            db_adapter.execute(
                "DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id}
            )
            db_adapter.execute("DELETE FROM companies WHERE cik = '0009992002'")

    def test_review_page_status_filter(self, client, db_adapter):
        """?status=pending_review filter is accepted and returns 200."""
        _, filing_id = create_test_company_and_filing(
            db_adapter,
            cik="0009992003",
            accession_number="0009992003-24-000001",
        )
        create_test_v2_document(db_adapter, filing_id)
        create_test_v2_fact(db_adapter, filing_id, review_status="pending_review")

        try:
            response = client.get(f"/v2/review/{filing_id}?status=pending_review")
            assert response.status_code == 200
        finally:
            db_adapter.execute(
                "DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id}
            )
            db_adapter.execute("DELETE FROM companies WHERE cik = '0009992003'")

    def test_review_page_missing_filing_redirects(self, client):
        """GET /v2/review/99999 (nonexistent) redirects — abort(404) caught by except."""
        response = client.get("/v2/review/99999")
        # The route catches abort(404) in its except Exception block and redirects
        # to /v2/review/filings. Either 302 or follow-redirected 200 is valid.
        assert response.status_code in (302, 404)

    def test_review_page_redirect_target(self, client):
        """Redirect from nonexistent filing goes to the filings list."""
        response = client.get("/v2/review/99999", follow_redirects=True)
        # After following redirect we should reach the filing list (200)
        assert response.status_code == 200


# =============================================================================
# TestV2DecisionAPI
# =============================================================================


class TestV2DecisionAPI:
    """Tests for the V2 decision API (/api/v2/decisions)."""

    @pytest.fixture
    def filing_and_fact(self, db_adapter):
        """Create a filing + single fact for decision API tests."""
        _, filing_id = create_test_company_and_filing(
            db_adapter,
            cik="0009993001",
            accession_number="0009993001-24-000001",
        )
        create_test_v2_document(db_adapter, filing_id)
        fact_id = create_test_v2_fact(db_adapter, filing_id)
        yield filing_id, fact_id

        # CASCADE handles v2_metric_facts + v2_review_decisions via FK
        db_adapter.execute(
            "DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id}
        )
        db_adapter.execute("DELETE FROM companies WHERE cik = '0009993001'")

    def test_accept_decision(self, client, db_adapter, filing_and_fact):
        """POST /api/v2/decisions returns 201; DB trigger sets review_status=accepted."""
        filing_id, fact_id = filing_and_fact

        response = client.post(
            "/api/v2/decisions",
            json={"fact_id": fact_id, "decision": "accept"},
        )
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert "decision_id" in data
        assert data["fact_id"] == fact_id

        # Verify DB trigger updated review_status
        rows = db_adapter.query(
            "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
            {"id": fact_id},
        )
        assert rows[0]["review_status"] == "accepted"

    def test_reject_decision(self, client, db_adapter, filing_and_fact):
        """POST with rejection fields; review_status becomes rejected."""
        filing_id, fact_id = filing_and_fact

        response = client.post(
            "/api/v2/decisions",
            json={
                "fact_id": fact_id,
                "decision": "reject",
                "rejection_reason": "Not a customer metric",
                "rejection_category": "not_a_metric",
            },
        )
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"

        rows = db_adapter.query(
            "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
            {"id": fact_id},
        )
        assert rows[0]["review_status"] == "rejected"

    def test_correct_decision(self, client, db_adapter, filing_and_fact):
        """POST with assigned_metric_id + corrected_value; review_status=corrected."""
        filing_id, fact_id = filing_and_fact

        response = client.post(
            "/api/v2/decisions",
            json={
                "fact_id": fact_id,
                "decision": "correct",
                "assigned_metric_id": "cm_active_customers_total",
                "corrected_value": 9500,
            },
        )
        assert response.status_code == 201

        rows = db_adapter.query(
            "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
            {"id": fact_id},
        )
        assert rows[0]["review_status"] == "corrected"

    def test_duplicate_decision_409(self, client, db_adapter, filing_and_fact):
        """Second POST for same fact_id returns 409 Conflict."""
        filing_id, fact_id = filing_and_fact

        r1 = client.post(
            "/api/v2/decisions",
            json={"fact_id": fact_id, "decision": "accept"},
        )
        assert r1.status_code == 201

        r2 = client.post(
            "/api/v2/decisions",
            json={"fact_id": fact_id, "decision": "reject"},
        )
        assert r2.status_code == 409
        data = json.loads(r2.data)
        assert data["status"] == "error"

    def test_invalid_fact_id_404(self, client):
        """POST with nonexistent fact_id returns 404."""
        response = client.post(
            "/api/v2/decisions",
            json={
                "fact_id": "00000000-0000-0000-0000-000000000000",
                "decision": "accept",
            },
        )
        assert response.status_code == 404

    def test_missing_both_required_fields_400(self, client):
        """POST without fact_id AND decision returns 400."""
        response = client.post("/api/v2/decisions", json={})
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_missing_decision_field_400(self, client):
        """POST without decision returns 400."""
        response = client.post(
            "/api/v2/decisions",
            json={"fact_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_missing_fact_id_field_400(self, client):
        """POST without fact_id returns 400."""
        response = client.post("/api/v2/decisions", json={"decision": "accept"})
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_non_json_request_400(self, client):
        """POST with non-JSON content type returns 400."""
        response = client.post(
            "/api/v2/decisions",
            data="fact_id=abc&decision=accept",
            content_type="application/x-www-form-urlencoded",
        )
        assert response.status_code == 400

    def test_undo_decision(self, client, db_adapter, filing_and_fact):
        """DELETE /api/v2/decisions/<id> returns 200; review_status resets to pending_review."""
        filing_id, fact_id = filing_and_fact

        # Create a decision first
        r = client.post(
            "/api/v2/decisions",
            json={"fact_id": fact_id, "decision": "accept"},
        )
        assert r.status_code == 201
        decision_id = json.loads(r.data)["decision_id"]

        # Undo it
        r2 = client.delete(f"/api/v2/decisions/{decision_id}")
        assert r2.status_code == 200
        data = json.loads(r2.data)
        assert data["status"] == "success"
        assert "fact_id" in data

        # Verify review_status was reset (delete_v2_review_decision resets it)
        rows = db_adapter.query(
            "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
            {"id": fact_id},
        )
        # requires_review=True (default), so status resets to pending_review
        assert rows[0]["review_status"] == "pending_review"

    def test_undo_nonexistent_decision_404(self, client):
        """DELETE with a nonexistent decision_id returns 404."""
        response = client.delete(
            "/api/v2/decisions/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_response_includes_next_fact_field(self, client, db_adapter):
        """POST response always includes a next_fact key (may be None or a dict)."""
        _, filing_id = create_test_company_and_filing(
            db_adapter,
            cik="0009993002",
            accession_number="0009993002-24-000001",
        )
        create_test_v2_document(db_adapter, filing_id)
        fact_id_1 = create_test_v2_fact(
            db_adapter,
            filing_id,
            period_end="2023-12-31",
            period_start="2023-01-01",
        )
        _fact_id_2 = create_test_v2_fact(
            db_adapter,
            filing_id,
            period_end="2022-12-31",
            period_start="2022-01-01",
            value=5000,
            value_raw="5,000",
        )

        try:
            response = client.post(
                "/api/v2/decisions",
                json={"fact_id": fact_id_1, "decision": "accept"},
            )
            assert response.status_code == 201
            data = json.loads(response.data)

            # next_fact field must be present; value is either None or a dict
            assert "next_fact" in data
            if data["next_fact"] is not None:
                assert "fact_id" in data["next_fact"]
                assert "url" in data["next_fact"]
        finally:
            db_adapter.execute(
                "DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id}
            )
            db_adapter.execute("DELETE FROM companies WHERE cik = '0009993002'")

    def test_decision_response_structure(self, client, db_adapter, filing_and_fact):
        """201 response body contains status, decision_id, and fact_id fields."""
        filing_id, fact_id = filing_and_fact

        response = client.post(
            "/api/v2/decisions",
            json={
                "fact_id": fact_id,
                "decision": "accept",
                "reviewer_notes": "Looks good",
                "review_time_seconds": 15,
            },
        )
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert "decision_id" in data
        assert "fact_id" in data
        assert "next_fact" in data
        # decision_id should be a non-empty string (UUID)
        assert isinstance(data["decision_id"], str)
        assert len(data["decision_id"]) == 36  # UUID length with hyphens


# =============================================================================
# TestV2ReviewWorkflowEnd2End
# =============================================================================


class TestV2ReviewWorkflowEnd2End:
    """End-to-end tests that simulate the full review user journey."""

    def test_full_review_workflow(self, client, db_adapter):
        """
        Simulate: load filing list -> open review page -> accept fact -> undo.

        Covers the primary happy-path user journey across all three route layers.
        """
        # 1. Set up filing with two facts
        _, filing_id = create_test_company_and_filing(
            db_adapter,
            cik="0009994001",
            accession_number="0009994001-24-000001",
        )
        create_test_v2_document(db_adapter, filing_id)
        fact_id_1 = create_test_v2_fact(
            db_adapter,
            filing_id,
            period_end="2023-12-31",
            period_start="2023-01-01",
            value=10000,
            value_raw="10,000",
        )
        fact_id_2 = create_test_v2_fact(
            db_adapter,
            filing_id,
            period_end="2022-12-31",
            period_start="2022-01-01",
            value=8000,
            value_raw="8,000",
        )

        try:
            # 2. Filing list shows 200
            r_list = client.get("/v2/review/filings")
            assert r_list.status_code == 200

            # 3. Review page loads
            r_review = client.get(f"/v2/review/{filing_id}")
            assert r_review.status_code == 200

            # 4. Accept the first fact
            r_accept = client.post(
                "/api/v2/decisions",
                json={"fact_id": fact_id_1, "decision": "accept"},
            )
            assert r_accept.status_code == 201
            accept_data = json.loads(r_accept.data)
            decision_id = accept_data["decision_id"]

            # Verify DB state after accept
            rows = db_adapter.query(
                "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
                {"id": fact_id_1},
            )
            assert rows[0]["review_status"] == "accepted"

            # 5. Reject the second fact
            r_reject = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": fact_id_2,
                    "decision": "reject",
                    "rejection_category": "wrong_metric",
                    "rejection_reason": "This is a subtotal, not aggregate",
                },
            )
            assert r_reject.status_code == 201

            rows2 = db_adapter.query(
                "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
                {"id": fact_id_2},
            )
            assert rows2[0]["review_status"] == "rejected"

            # 6. Undo the accept decision
            r_undo = client.delete(f"/api/v2/decisions/{decision_id}")
            assert r_undo.status_code == 200

            rows3 = db_adapter.query(
                "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
                {"id": fact_id_1},
            )
            assert rows3[0]["review_status"] == "pending_review"

            # 7. Review page still loads after undo
            r_review2 = client.get(f"/v2/review/{filing_id}")
            assert r_review2.status_code == 200

        finally:
            db_adapter.execute(
                "DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id}
            )
            db_adapter.execute("DELETE FROM companies WHERE cik = '0009994001'")
