"""Integration tests for the admin review tool (PR 2).

Covers:
- @admin_required gate on each endpoint (anonymous, reviewer, admin)
- Suppressed-images endpoint happy path (one image of each suppression reason)
- By-reviewer endpoint happy path
- Override POST: new admin row, with-supersedes row, missing override_reason → 400
- Override DELETE: happy path, 404, 400 on non-admin row
- admin_audit_log row written for each write

Auth is set via direct monkeypatch of ``src.auth.load_user.load_session_user`` so we
don't need a live OAuth flow.
"""

from __future__ import annotations

import uuid as _uuid

import pytest

from src.auth.sessions import SessionUser
from tests.integration.conftest import (
    create_test_company_and_filing,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user_id(test_db_adapter):
    rows = test_db_adapter.query(
        """
        INSERT INTO auth_users (normalized_email, role, account_status, display_name)
        VALUES ('admin@test.local', 'admin', 'active', 'Admin User')
        ON CONFLICT (normalized_email) DO UPDATE SET role='admin', account_status='active'
        RETURNING id::text AS id
        """,
        {},
    )
    return rows[0]["id"]


@pytest.fixture
def reviewer_user_id(test_db_adapter):
    rows = test_db_adapter.query(
        """
        INSERT INTO auth_users (normalized_email, role, account_status, display_name)
        VALUES ('reviewer@test.local', 'reviewer', 'active', 'Reviewer User')
        ON CONFLICT (normalized_email) DO UPDATE SET role='reviewer', account_status='active'
        RETURNING id::text AS id
        """,
        {},
    )
    return rows[0]["id"]


@pytest.fixture
def app(monkeypatch, test_db_adapter):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("DATABASE_URL", test_db_adapter.connection_string)
    monkeypatch.setenv("FILINGS_API_KEY", "test-key")

    from src.web.app import create_app

    app = create_app("testing")
    # TestingConfig.DATABASE_URL is frozen at module-import time (before xdist
    # rewrites TEST_DATABASE_URL to the worker-specific DB). Override here so
    # the Flask test client hits the same database as test_db_adapter.
    app.config["DATABASE_URL"] = test_db_adapter.connection_string
    app.config["TESTING"] = True
    return app


def _client_as(app, user: SessionUser | None):
    """Return a test client with g.user pre-set to the given SessionUser (or None)."""

    @app.before_request
    def _inject_user():
        from flask import g

        g.user = user

    return app.test_client()


def _admin_user(uid: str) -> SessionUser:
    return SessionUser(
        id=uid,
        email="admin@test.local",
        display_name="Admin",
        role="admin",
        account_status="active",
    )


def _reviewer_user(uid: str) -> SessionUser:
    return SessionUser(
        id=uid,
        email="reviewer@test.local",
        display_name="Reviewer",
        role="reviewer",
        account_status="active",
    )


def _insert_image(
    db,
    filing_id: int,
    *,
    classification="chart",
    review_status="pending",
    predicted_relevance=0.5,
    filename="img1.png",
) -> str:
    rows = db.query(
        """
        INSERT INTO v2_image_assets (
            filing_id, filename, dom_locator, classification, review_status, predicted_relevance, processed
        ) VALUES (
            %(filing_id)s, %(filename)s, '/html/body/img[1]', %(classification)s, %(review_status)s,
            %(predicted_relevance)s, true
        )
        RETURNING img_id::text AS img_id
        """,
        {
            "filing_id": filing_id,
            "filename": filename,
            "classification": classification,
            "review_status": review_status,
            "predicted_relevance": predicted_relevance,
        },
    )
    return rows[0]["img_id"]


def _insert_confirmation(
    db,
    img_id: str,
    reviewer_id: str,
    *,
    decision="accept",
    detected_metric_id=None,
    confirmed_metric_id="cm_customers_period_end",
    rejection_reason=None,
    override_reason=None,
    supersedes_id=None,
) -> str:
    rows = db.query(
        """
        INSERT INTO v2_image_metric_confirmations (
            img_id, reviewer_id, decision, detected_metric_id, confirmed_metric_id,
            rejection_reason, override_reason, supersedes_confirmation_id
        ) VALUES (
            %(img_id)s, %(reviewer_id)s, %(decision)s, %(detected_metric_id)s, %(confirmed_metric_id)s,
            %(rejection_reason)s, %(override_reason)s, %(supersedes_id)s
        )
        RETURNING id::text AS id
        """,
        {
            "img_id": img_id,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "detected_metric_id": detected_metric_id,
            "confirmed_metric_id": confirmed_metric_id,
            "rejection_reason": rejection_reason,
            "override_reason": override_reason,
            "supersedes_id": supersedes_id,
        },
    )
    return rows[0]["id"]


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


class TestAdminGate:
    def test_anonymous_blocked_on_index(self, app, clean_db):
        client = _client_as(app, None)
        resp = client.get("/admin/review")
        assert resp.status_code == 403

    def test_reviewer_blocked_on_suppressed(self, app, clean_db, reviewer_user_id):
        client = _client_as(app, _reviewer_user(reviewer_user_id))
        resp = client.get("/admin/review/suppressed")
        assert resp.status_code == 403

    def test_reviewer_blocked_on_by_reviewer(self, app, clean_db, reviewer_user_id):
        client = _client_as(app, _reviewer_user(reviewer_user_id))
        resp = client.get("/admin/review/by-reviewer?reviewer_id=anyone")
        assert resp.status_code == 403

    def test_reviewer_blocked_on_override_post(self, app, clean_db, reviewer_user_id):
        client = _client_as(app, _reviewer_user(reviewer_user_id))
        resp = client.post("/api/admin/image-decision-override", json={})
        assert resp.status_code == 403

    def test_admin_allowed_on_index(self, app, clean_db, admin_user_id):
        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.get("/admin/review")
        assert resp.status_code == 200
        # PR 3: page now renders the full composite template with both tabs.
        assert b"Admin Review Tool" in resp.data
        assert b"Suppressed Images" in resp.data
        assert b"Reviewer Audit" in resp.data
        # Override modal markup is present
        assert b"overrideModal" in resp.data
        # JS asset is referenced
        assert b"admin_review.js" in resp.data


# ---------------------------------------------------------------------------
# Suppressed images
# ---------------------------------------------------------------------------


class TestSuppressedEndpoint:
    def test_returns_skipped_image(self, app, clean_db, admin_user_id):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image(
            clean_db, filing_id, review_status="skipped", predicted_relevance=0.5
        )

        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.get("/admin/review/suppressed?suppression_reason=skipped")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] >= 1
        ids = [r["img_id"] for r in body["images"]]
        assert img_id in ids

    def test_returns_low_score_image(self, app, clean_db, admin_user_id):
        _, filing_id = create_test_company_and_filing(
            clean_db, accession_number="0001234567-24-000002"
        )
        img_id = _insert_image(
            clean_db, filing_id, review_status="pending", predicted_relevance=0.05
        )

        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.get("/admin/review/suppressed?suppression_reason=low_score")
        assert resp.status_code == 200
        body = resp.get_json()
        ids = [r["img_id"] for r in body["images"]]
        assert img_id in ids

    def test_returns_hidden_classification(self, app, clean_db, admin_user_id):
        _, filing_id = create_test_company_and_filing(
            clean_db, accession_number="0001234567-24-000003"
        )
        img_id = _insert_image(clean_db, filing_id, classification="decorative")

        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.get("/admin/review/suppressed?suppression_reason=hidden_classification")
        assert resp.status_code == 200
        body = resp.get_json()
        ids = [r["img_id"] for r in body["images"]]
        assert img_id in ids

    def test_rejects_invalid_reason(self, app, clean_db, admin_user_id):
        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.get("/admin/review/suppressed?suppression_reason=not_a_real_reason")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# By-reviewer
# ---------------------------------------------------------------------------


class TestByReviewerEndpoint:
    def test_requires_reviewer_id(self, app, clean_db, admin_user_id):
        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.get("/admin/review/by-reviewer")
        assert resp.status_code == 400

    def test_returns_reviewer_decisions(self, app, clean_db, admin_user_id, reviewer_user_id):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id)
        _insert_confirmation(clean_db, img_id, reviewer_user_id)

        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.get(f"/admin/review/by-reviewer?reviewer_id={reviewer_user_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] >= 1


# ---------------------------------------------------------------------------
# Override POST
# ---------------------------------------------------------------------------


class TestOverridePost:
    def test_requires_override_reason(self, app, clean_db, admin_user_id):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id)
        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.post(
            "/api/admin/image-decision-override",
            json={
                "img_id": img_id,
                "decisions": [
                    {"decision": "add", "confirmed_metric_id": "cm_customers_period_end"}
                ],
                # missing override_reason
            },
        )
        assert resp.status_code == 400
        assert "override_reason" in resp.get_json()["error"]

    def test_writes_override_row_and_audit(self, app, clean_db, admin_user_id):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id)
        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.post(
            "/api/admin/image-decision-override",
            json={
                "img_id": img_id,
                "decisions": [
                    {"decision": "add", "confirmed_metric_id": "cm_customers_period_end"}
                ],
                "override_reason": "admin flagged a missed customer-count chart",
            },
        )
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["confirmation_ids"]) == 1

        # Row exists with override_reason
        rows = clean_db.query(
            "SELECT override_reason, reviewer_id, supersedes_confirmation_id "
            "FROM v2_image_metric_confirmations WHERE img_id = %(img)s",
            {"img": img_id},
        )
        assert len(rows) == 1
        assert "admin flagged" in rows[0]["override_reason"]
        assert rows[0]["reviewer_id"] == admin_user_id
        assert rows[0]["supersedes_confirmation_id"] is None

        # admin_audit_log: review_suppressed (no supersedes)
        audits = clean_db.query(
            "SELECT action_type FROM admin_audit_log WHERE actor_user_id = %(uid)s "
            "ORDER BY created_at DESC LIMIT 5",
            {"uid": admin_user_id},
        )
        action_types = [a["action_type"] for a in audits]
        assert "image.admin_review_suppressed" in action_types

    def test_writes_supersedes_override(self, app, clean_db, admin_user_id, reviewer_user_id):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id)
        # Reviewer's original row
        reviewer_conf_id = _insert_confirmation(
            clean_db,
            img_id,
            reviewer_user_id,
            decision="reject",
            confirmed_metric_id=None,
            detected_metric_id="cm_customers_period_end",
            rejection_reason="not_present",
        )

        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.post(
            "/api/admin/image-decision-override",
            json={
                "img_id": img_id,
                "decisions": [
                    {
                        "decision": "accept",
                        "detected_metric_id": "cm_customers_period_end",
                        "confirmed_metric_id": "cm_customers_period_end",
                    }
                ],
                "override_reason": "reviewer rejected but chart clearly shows customers",
                "supersedes_confirmation_id": reviewer_conf_id,
            },
        )
        assert resp.status_code == 200, resp.data

        # Both rows exist (reviewer's + admin's)
        rows = clean_db.query(
            "SELECT id::text AS id, reviewer_id, override_reason, "
            "supersedes_confirmation_id::text AS supersedes "
            "FROM v2_image_metric_confirmations WHERE img_id = %(img)s",
            {"img": img_id},
        )
        assert len(rows) == 2
        admin_row = [r for r in rows if r["override_reason"]]
        assert len(admin_row) == 1
        assert admin_row[0]["supersedes"] == reviewer_conf_id
        assert admin_row[0]["reviewer_id"] == admin_user_id

        # Audit log has override_create action
        audits = clean_db.query(
            "SELECT action_type FROM admin_audit_log WHERE actor_user_id = %(uid)s",
            {"uid": admin_user_id},
        )
        action_types = [a["action_type"] for a in audits]
        assert "image.admin_override_create" in action_types


# ---------------------------------------------------------------------------
# Override DELETE
# ---------------------------------------------------------------------------


class TestOverrideDelete:
    def test_delete_admin_override(self, app, clean_db, admin_user_id):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id)
        override_id = _insert_confirmation(
            clean_db,
            img_id,
            admin_user_id,
            decision="add",
            confirmed_metric_id="cm_customers_period_end",
            override_reason="admin added a missed metric",
        )

        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.delete(f"/api/admin/image-decision-override/{override_id}")
        assert resp.status_code == 200, resp.data

        # Row gone
        rows = clean_db.query(
            "SELECT 1 FROM v2_image_metric_confirmations WHERE id = %(id)s",
            {"id": override_id},
        )
        assert rows == []

        # Audit
        audits = clean_db.query(
            "SELECT action_type FROM admin_audit_log WHERE actor_user_id = %(uid)s",
            {"uid": admin_user_id},
        )
        assert "image.admin_override_undo" in [a["action_type"] for a in audits]

    def test_delete_404_on_missing(self, app, clean_db, admin_user_id):
        client = _client_as(app, _admin_user(admin_user_id))
        bogus = str(_uuid.uuid4())
        resp = client.delete(f"/api/admin/image-decision-override/{bogus}")
        assert resp.status_code == 404

    def test_delete_400_on_non_admin_row(self, app, clean_db, admin_user_id, reviewer_user_id):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id)
        reviewer_conf_id = _insert_confirmation(
            clean_db,
            img_id,
            reviewer_user_id,
            decision="accept",
            confirmed_metric_id="cm_customers_period_end",
            # No override_reason — this is a reviewer row
        )

        client = _client_as(app, _admin_user(admin_user_id))
        resp = client.delete(f"/api/admin/image-decision-override/{reviewer_conf_id}")
        assert resp.status_code == 400
        assert "not an admin override" in resp.get_json()["error"]
