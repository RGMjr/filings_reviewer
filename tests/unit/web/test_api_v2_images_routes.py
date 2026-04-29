"""
Unit tests for V2 image-level skip/unskip routes in api_unified.py.

The per-metric A/R/C/Add/Skip flow that replaced the legacy
/api/v2/image-decisions endpoints is covered by the integration tests
in tests/integration/web/test_image_metric_confirmations.py.

Also covers the pure-Python stale-decision hash logic in DatabaseAdapter
(_compute_image_content_hash, _derive_is_stale_vs_decision).
"""

from unittest.mock import MagicMock

import pytest

from src.infra.db import DatabaseAdapter
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


class TestReopenImageCandidateV2:
    """Per gh-293 — flip legacy review_status='reviewed' back to 'pending'."""

    def test_reopen_success(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.reopen_image_candidate_v2.return_value = True

        resp = client.post(
            f"/api/v2/image-candidates/{IMG_ID}/reopen",
            headers={"X-Reviewer-Id": "RGM"},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["img_id"] == IMG_ID
        assert body["review_status"] == "pending"
        mock_db.reopen_image_candidate_v2.assert_called_once_with(IMG_ID)

    def test_reopen_missing_reviewer_returns_400(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        resp = client.post(f"/api/v2/image-candidates/{IMG_ID}/reopen")

        assert resp.status_code == 400
        mock_db.reopen_image_candidate_v2.assert_not_called()

    def test_reopen_not_reviewed_returns_404(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)
        mock_db.reopen_image_candidate_v2.return_value = False

        resp = client.post(
            f"/api/v2/image-candidates/{IMG_ID}/reopen",
            headers={"X-Reviewer-Id": "RGM"},
        )

        assert resp.status_code == 404


class TestComputeImageContentHash:
    """Unit tests for the locked hash recipe (sha256 + unit-separator)."""

    def test_same_inputs_produce_same_hash(self):
        h1 = DatabaseAdapter._compute_image_content_hash("some ocr text", '{"k": 1}')
        h2 = DatabaseAdapter._compute_image_content_hash("some ocr text", '{"k": 1}')
        assert h1 == h2

    def test_different_ocr_text_produces_different_hash(self):
        h1 = DatabaseAdapter._compute_image_content_hash("old ocr", None)
        h2 = DatabaseAdapter._compute_image_content_hash("new ocr", None)
        assert h1 != h2

    def test_different_chart_data_produces_different_hash(self):
        h1 = DatabaseAdapter._compute_image_content_hash(None, '{"v": 1}')
        h2 = DatabaseAdapter._compute_image_content_hash(None, '{"v": 2}')
        assert h1 != h2

    def test_none_inputs_produce_stable_hash(self):
        # Two calls with all-None inputs must agree (idempotent empty hash).
        h1 = DatabaseAdapter._compute_image_content_hash(None, None)
        h2 = DatabaseAdapter._compute_image_content_hash(None, None)
        assert h1 == h2

    def test_returns_64_char_hex_string(self):
        h = DatabaseAdapter._compute_image_content_hash("abc", "def")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestDeriveIsStalVsDecision:
    """Unit tests for the stale-decision derivation (no DB required)."""

    def _hash_for(self, ocr: str | None, chart: str | None) -> str:
        return DatabaseAdapter._compute_image_content_hash(ocr, chart)

    def test_null_decided_against_hash_returns_false(self):
        """Grandfather clause: NULL hash → stale=False."""
        row: dict = {
            "decided_against_hash": None,
            "current_ocr_text": "some text",
            "current_chart_data_json": None,
        }
        assert DatabaseAdapter._derive_is_stale_vs_decision(row) is False

    def test_missing_decided_against_hash_key_returns_false(self):
        """Missing key is treated the same as NULL (grandfather clause)."""
        row: dict = {
            "current_ocr_text": "some text",
            "current_chart_data_json": None,
        }
        assert DatabaseAdapter._derive_is_stale_vs_decision(row) is False

    def test_matching_hash_returns_false(self):
        """Hash stored at decision time matches current content → not stale."""
        ocr = "Total payment volume $387.7 billion"
        chart = None
        stored_hash = self._hash_for(ocr, chart)
        row: dict = {
            "decided_against_hash": stored_hash,
            "current_ocr_text": ocr,
            "current_chart_data_json": chart,
        }
        assert DatabaseAdapter._derive_is_stale_vs_decision(row) is False

    def test_changed_ocr_text_returns_true(self):
        """OCR text changed since decision → stale=True."""
        old_ocr = "old ocr text"
        new_ocr = "new ocr text — content updated after re-extraction"
        stored_hash = self._hash_for(old_ocr, None)
        row: dict = {
            "decided_against_hash": stored_hash,
            "current_ocr_text": new_ocr,
            "current_chart_data_json": None,
        }
        assert DatabaseAdapter._derive_is_stale_vs_decision(row) is True

    def test_changed_chart_data_returns_true(self):
        """Chart data changed since decision → stale=True."""
        old_chart = '{"v": 1}'
        new_chart = '{"v": 2, "extra": true}'
        stored_hash = self._hash_for(None, old_chart)
        row: dict = {
            "decided_against_hash": stored_hash,
            "current_ocr_text": None,
            "current_chart_data_json": new_chart,
        }
        assert DatabaseAdapter._derive_is_stale_vs_decision(row) is True
