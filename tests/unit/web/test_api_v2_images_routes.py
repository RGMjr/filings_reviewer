"""
Unit tests for V2 image decision API routes in api_unified.py.

Covers /api/v2/image-decisions (POST, DELETE) and /api/v2/image-candidates/<uuid>/
{skip,unskip}. Uses mocked DB to isolate route logic — db method correctness is
covered by tests/integration/test_db_v2_image_methods.py.
"""

import json
from unittest.mock import MagicMock

import pytest

from src.web.app import create_app

IMG_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def app():
    app = create_app(
        config_name="testing",
        config_override={"DATABASE_URL": "postgresql://test:test@localhost/test"},
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db(app):
    db = MagicMock()
    app.config["_test_db"] = db
    with app.app_context():
        from src.web import app as app_module

        app_module.get_db = lambda: db
    return db


def _patch_get_db(monkeypatch, mock_db):
    monkeypatch.setattr("src.web.routes.api_unified.get_db", lambda: mock_db)


class TestCreateImageDecisionV2:
    def test_relevant_decision_success(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = {
            "img_id": IMG_ID,
            "filing_id": 5,
            "review_status": "pending",
            "decision": None,
        }
        mock_db.insert_image_review_decision_v2.return_value = 456
        mock_db.get_next_pending_image_candidate_v2.return_value = None

        resp = client.post(
            "/api/v2/image-decisions",
            data=json.dumps(
                {
                    "img_id": IMG_ID,
                    "decision": "relevant",
                    "chart_type": "cohort_table",
                }
            ),
            content_type="application/json",
        )

        assert resp.status_code == 201
        body = resp.get_json()
        assert body["status"] == "success"
        assert body["decision_id"] == 456
        mock_db.insert_image_review_decision_v2.assert_called_once()

    def test_reviewer_id_is_persisted(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = {
            "img_id": IMG_ID,
            "filing_id": 5,
            "review_status": "pending",
            "decision": None,
        }
        mock_db.insert_image_review_decision_v2.return_value = 789
        mock_db.get_next_pending_image_candidate_v2.return_value = None

        resp = client.post(
            "/api/v2/image-decisions",
            data=json.dumps(
                {
                    "img_id": IMG_ID,
                    "decision": "relevant",
                    "chart_type": "cohort_table",
                    "reviewer_id": "alice@example.com",
                }
            ),
            content_type="application/json",
        )

        assert resp.status_code == 201
        call_kwargs = mock_db.insert_image_review_decision_v2.call_args.kwargs
        assert call_kwargs["reviewer_id"] == "alice@example.com"

    def test_reviewer_id_defaults_to_anonymous(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = {
            "img_id": IMG_ID,
            "filing_id": 5,
            "review_status": "pending",
            "decision": None,
        }
        mock_db.insert_image_review_decision_v2.return_value = 790
        mock_db.get_next_pending_image_candidate_v2.return_value = None

        resp = client.post(
            "/api/v2/image-decisions",
            data=json.dumps(
                {
                    "img_id": IMG_ID,
                    "decision": "relevant",
                    "chart_type": "cohort_table",
                }
            ),
            content_type="application/json",
        )

        assert resp.status_code == 201
        call_kwargs = mock_db.insert_image_review_decision_v2.call_args.kwargs
        assert call_kwargs["reviewer_id"] == "anonymous"

    def test_missing_img_id_returns_400(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        resp = client.post(
            "/api/v2/image-decisions",
            data=json.dumps({"decision": "relevant", "chart_type": "cohort_table"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "img_id" in resp.get_json()["message"]

    def test_invalid_uuid_returns_400(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        resp = client.post(
            "/api/v2/image-decisions",
            data=json.dumps(
                {
                    "img_id": "not-a-uuid",
                    "decision": "relevant",
                    "chart_type": "cohort_table",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "UUID" in resp.get_json()["message"]

    def test_candidate_not_found_returns_404(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = None

        resp = client.post(
            "/api/v2/image-decisions",
            data=json.dumps(
                {
                    "img_id": IMG_ID,
                    "decision": "relevant",
                    "chart_type": "cohort_table",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_already_decided_returns_409(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = {
            "img_id": IMG_ID,
            "filing_id": 5,
            "review_status": "reviewed",
            "decision": "relevant",
        }

        resp = client.post(
            "/api/v2/image-decisions",
            data=json.dumps(
                {
                    "img_id": IMG_ID,
                    "decision": "relevant",
                    "chart_type": "cohort_table",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 409


class TestSkipImageCandidateV2:
    def test_skip_success(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = {
            "img_id": IMG_ID,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.skip_image_candidate_v2.return_value = True
        mock_db.get_next_pending_image_candidate_v2.return_value = None

        resp = client.post(f"/api/v2/image-candidates/{IMG_ID}/skip")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        assert body["skipped_img_id"] == IMG_ID

    def test_skip_unknown_img_returns_404(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = None

        resp = client.post(f"/api/v2/image-candidates/{IMG_ID}/skip")
        assert resp.status_code == 404


class TestUnskipImageCandidateV2:
    def test_unskip_success(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = {
            "img_id": IMG_ID,
            "filing_id": 5,
            "review_status": "skipped",
        }
        mock_db.unskip_image_candidate_v2.return_value = True

        resp = client.post(f"/api/v2/image-candidates/{IMG_ID}/unskip")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        assert body["img_id"] == IMG_ID
        assert "img_id=" in body["url"]

    def test_unskip_non_skipped_returns_400(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.get_image_review_candidate_v2.return_value = {
            "img_id": IMG_ID,
            "filing_id": 5,
            "review_status": "reviewed",
        }

        resp = client.post(f"/api/v2/image-candidates/{IMG_ID}/unskip")
        assert resp.status_code == 400


class TestDeleteImageDecisionV2:
    def test_delete_success(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.query.return_value = [{"img_id": IMG_ID}]
        mock_db.delete_image_review_decision_v2.return_value = True

        resp = client.delete("/api/v2/image-decisions/456")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        assert body["img_id"] == IMG_ID

    def test_delete_unknown_decision_returns_404(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.query.return_value = []

        resp = client.delete("/api/v2/image-decisions/999")
        assert resp.status_code == 404
