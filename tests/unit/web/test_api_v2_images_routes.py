"""
Unit tests for V2 image-level skip/unskip routes in api_unified.py.

The per-metric A/R/C/Add/Skip flow that replaced the legacy
/api/v2/image-decisions endpoints is covered by the integration tests
in tests/integration/web/test_image_metric_confirmations.py.
"""

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


def _patch_get_db(monkeypatch, mock_db):
    monkeypatch.setattr("src.web.routes.api_unified.get_db", lambda: mock_db)


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
