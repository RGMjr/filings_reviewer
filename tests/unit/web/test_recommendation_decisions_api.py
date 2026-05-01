"""Unit tests for the recommendation-decisions endpoints.

Covers:
  - POST /api/v2/extraction/recommendation-decisions — admin gate, reviewer gate,
    field validation, upsert wiring, change-of-mind path.
  - DELETE /api/v2/extraction/recommendation-decisions/<uuid> — owner scope
    (reviewer A can't undo reviewer B's decision via 404), admin gate.

The admin gate is the new transitional `require_admin` decorator on
`src.web.middleware`; tests set ADMIN_USER_IDS via monkeypatch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "RGM,admin@example.com")
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
    with patch("src.web.routes.api_unified.get_db") as mock_get_db:
        db = MagicMock()
        db.upsert_recommendation_decision.return_value = {
            "id": uuid.uuid4(),
            "metric_id": "cm_x",
            "rule": "exclusion_pattern",
            "decision_key": "accounts receivable",
            "decision": "accepted",
            "reviewer_id": "RGM",
            "reviewer_note": None,
            "pr_number": None,
            "pr_url": None,
            "created_at": datetime(2026, 5, 1, 20, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 1, 20, tzinfo=UTC),
        }
        db.delete_recommendation_decision.return_value = True
        db.insert_audit_log.return_value = None
        mock_get_db.return_value = db
        yield db


_POST = "/api/v2/extraction/recommendation-decisions"


def _delete_url(decision_id: str) -> str:
    return f"/api/v2/extraction/recommendation-decisions/{decision_id}"


_VALID_BODY = {
    "metric_id": "cm_x",
    "rule": "exclusion_pattern",
    "decision_key": "accounts receivable",
    "decision": "accepted",
    "reviewer_id": "RGM",
}


# ---------------------------------------------------------------------------
# POST gates
# ---------------------------------------------------------------------------


class TestPostGates:
    def test_missing_reviewer_id_returns_403(self, client, mock_db):
        body = {k: v for k, v in _VALID_BODY.items() if k != "reviewer_id"}
        resp = client.post(_POST, json=body)
        assert resp.status_code == 403
        assert resp.get_json()["error"] in {"admin_required", "reviewer_name_required"}
        mock_db.upsert_recommendation_decision.assert_not_called()

    def test_blocklisted_reviewer_returns_403(self, client, mock_db):
        resp = client.post(_POST, json={**_VALID_BODY, "reviewer_id": "anonymous"})
        assert resp.status_code == 403
        mock_db.upsert_recommendation_decision.assert_not_called()

    def test_non_admin_returns_403(self, client, mock_db, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", "OTHER_ADMIN")
        resp = client.post(_POST, json=_VALID_BODY)
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["error"] == "admin_required"
        mock_db.upsert_recommendation_decision.assert_not_called()

    def test_missing_admin_env_returns_403(self, client, mock_db, monkeypatch):
        monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
        resp = client.post(_POST, json=_VALID_BODY)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "admin_required"


# ---------------------------------------------------------------------------
# POST validation
# ---------------------------------------------------------------------------


class TestPostValidation:
    def test_unknown_rule_returns_400(self, client, mock_db):
        resp = client.post(_POST, json={**_VALID_BODY, "rule": "made_up_rule"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"] == "validation_failed"
        assert "rule" in body["fields"]

    def test_unknown_decision_returns_400(self, client, mock_db):
        resp = client.post(_POST, json={**_VALID_BODY, "decision": "wishywashy"})
        assert resp.status_code == 400
        assert "decision" in resp.get_json()["fields"]

    def test_missing_metric_id_returns_400(self, client, mock_db):
        body = {k: v for k, v in _VALID_BODY.items() if k != "metric_id"}
        resp = client.post(_POST, json=body)
        assert resp.status_code == 400
        assert "metric_id" in resp.get_json()["fields"]

    def test_missing_decision_key_returns_400(self, client, mock_db):
        body = {k: v for k, v in _VALID_BODY.items() if k != "decision_key"}
        resp = client.post(_POST, json=body)
        assert resp.status_code == 400
        assert "decision_key" in resp.get_json()["fields"]

    def test_oversized_note_returns_400(self, client, mock_db):
        big = "x" * 1001
        resp = client.post(_POST, json={**_VALID_BODY, "reviewer_note": big})
        assert resp.status_code == 400
        assert "reviewer_note" in resp.get_json()["fields"]

    def test_non_string_note_returns_400(self, client, mock_db):
        resp = client.post(_POST, json={**_VALID_BODY, "reviewer_note": 123})
        assert resp.status_code == 400
        assert "reviewer_note must be a string" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# POST happy path / upsert wiring
# ---------------------------------------------------------------------------


class TestPostUpsert:
    def test_returns_200_with_serialized_row(self, client, mock_db):
        resp = client.post(_POST, json=_VALID_BODY)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["decision"] == "accepted"
        assert body["reviewer_id"] == "RGM"
        # ID and timestamps are JSON-serialized strings.
        uuid.UUID(body["id"])
        assert "T" in body["created_at"]

    def test_calls_db_upsert_with_correct_args(self, client, mock_db):
        client.post(_POST, json={**_VALID_BODY, "reviewer_note": "looks right"})
        mock_db.upsert_recommendation_decision.assert_called_once_with(
            metric_id="cm_x",
            rule="exclusion_pattern",
            decision_key="accounts receivable",
            decision="accepted",
            reviewer_id="RGM",
            reviewer_note="looks right",
        )

    def test_empty_note_string_passes_none_to_db(self, client, mock_db):
        client.post(_POST, json={**_VALID_BODY, "reviewer_note": "   "})
        kwargs = mock_db.upsert_recommendation_decision.call_args.kwargs
        assert kwargs["reviewer_note"] is None


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


class TestDelete:
    def test_returns_200_when_owner_deletes(self, client, mock_db):
        decision_id = str(uuid.uuid4())
        resp = client.delete(_delete_url(decision_id), json={"reviewer_id": "RGM"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["id"] == decision_id
        mock_db.delete_recommendation_decision.assert_called_once_with(decision_id, "RGM")

    def test_returns_404_when_not_owner_or_missing(self, client, mock_db):
        mock_db.delete_recommendation_decision.return_value = False
        decision_id = str(uuid.uuid4())
        resp = client.delete(_delete_url(decision_id), json={"reviewer_id": "RGM"})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "not_found_or_not_owner"

    def test_non_admin_returns_403(self, client, mock_db, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", "OTHER_ADMIN")
        resp = client.delete(_delete_url(str(uuid.uuid4())), json={"reviewer_id": "RGM"})
        assert resp.status_code == 403
        mock_db.delete_recommendation_decision.assert_not_called()

    def test_non_uuid_path_returns_404(self, client, mock_db):
        resp = client.delete(
            "/api/v2/extraction/recommendation-decisions/not-a-uuid",
            json={"reviewer_id": "RGM"},
        )
        # Flask <uuid:> converter rejects before handler.
        assert resp.status_code == 404
        mock_db.delete_recommendation_decision.assert_not_called()
