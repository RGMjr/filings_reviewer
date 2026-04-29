"""
Unit tests for bulk image-candidate endpoints in api_unified.py:
  POST /api/v2/image-candidates/bulk-reject
  POST /api/v2/image-candidates/bulk-undo
"""

from unittest.mock import MagicMock

import pytest

from src.web.app import create_app

IMG_ID_1 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
IMG_ID_2 = "11111111-2222-3333-4444-555555555555"
FILING_ID = 7
REVIEWER = "RGM"


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


def _make_candidate(img_id, detected_metrics=None, review_status="pending"):
    return {
        "img_id": img_id,
        "filing_id": FILING_ID,
        "review_status": review_status,
        "detected_metrics": detected_metrics or [],
    }


# =============================================================================
# bulk-reject tests
# =============================================================================


class TestBulkRejectImageCandidates:
    def test_success_zero_metric_images_sentinel_path(self, client, monkeypatch):
        """Images with no detected metrics get the sentinel no_relevant_metrics row."""
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        mock_db.get_image_review_candidate_v2.return_value = _make_candidate(
            IMG_ID_1, detected_metrics=[]
        )
        mock_db.insert_image_metric_confirmations.return_value = 1
        mock_db.skip_image_candidate_v2.return_value = True
        mock_db.get_pending_image_candidates_v2.return_value = []

        resp = client.post(
            "/api/v2/image-candidates/bulk-reject",
            json={"image_ids": [IMG_ID_1], "reviewer_id": REVIEWER},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["processed"] == 1
        assert body["results"][0]["status"] == "rejected"

        # Confirm sentinel decision was written
        call_args = mock_db.insert_image_metric_confirmations.call_args
        decisions = call_args[0][1]  # positional arg index 1
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "reject"
        assert decisions[0]["rejection_reason"] == "no_relevant_metrics"
        assert decisions[0]["detected_metric_id"] is None

        mock_db.skip_image_candidate_v2.assert_called_once_with(IMG_ID_1)

    def test_success_with_detected_metric_images(self, client, monkeypatch):
        """Images with detected metrics get per-metric reject rows (skipping accepted ones)."""
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        detected = [
            {"metric_id": "cm_customer_retention_rate"},
            {"metric_id": "cm_customers_period_end_by_tenure"},
        ]
        mock_db.get_image_review_candidate_v2.return_value = _make_candidate(
            IMG_ID_1, detected_metrics=detected
        )
        # No existing accepted confirmations
        mock_db.get_image_metric_confirmations.return_value = []
        mock_db.insert_image_metric_confirmations.return_value = 2
        mock_db.skip_image_candidate_v2.return_value = True
        mock_db.get_pending_image_candidates_v2.return_value = []

        resp = client.post(
            "/api/v2/image-candidates/bulk-reject",
            json={"image_ids": [IMG_ID_1], "reviewer_id": REVIEWER},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["results"][0]["status"] == "rejected"

        call_args = mock_db.insert_image_metric_confirmations.call_args
        decisions = call_args[0][1]
        assert len(decisions) == 2
        for d in decisions:
            assert d["decision"] == "reject"
            assert d["rejection_reason"] == "not_present"
        mock_db.skip_image_candidate_v2.assert_called_once_with(IMG_ID_1)

    def test_missing_reviewer_id_returns_403(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        resp = client.post(
            "/api/v2/image-candidates/bulk-reject",
            json={"image_ids": [IMG_ID_1]},
        )

        assert resp.status_code == 403
        body = resp.get_json()
        assert body["error"] == "reviewer_name_required"
        mock_db.insert_image_metric_confirmations.assert_not_called()

    def test_missing_image_ids_returns_400(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        resp = client.post(
            "/api/v2/image-candidates/bulk-reject",
            json={"reviewer_id": REVIEWER},
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert "image_ids" in body["error"]

    def test_blocked_reviewer_id_returns_403(self, client, monkeypatch):
        """Blocklisted reviewer IDs (e.g. 'anonymous') are rejected."""
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        resp = client.post(
            "/api/v2/image-candidates/bulk-reject",
            json={"image_ids": [IMG_ID_1], "reviewer_id": "anonymous"},
        )

        assert resp.status_code == 403

    def test_already_accepted_metrics_are_skipped(self, client, monkeypatch):
        """If all detected metrics are already accepted, result is 'skipped: already fully decided'."""
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        detected = [{"metric_id": "cm_customer_retention_rate"}]
        mock_db.get_image_review_candidate_v2.return_value = _make_candidate(
            IMG_ID_1, detected_metrics=detected
        )
        # Already accepted
        mock_db.get_image_metric_confirmations.return_value = [
            {"detected_metric_id": "cm_customer_retention_rate", "decision": "accept"},
        ]
        mock_db.get_pending_image_candidates_v2.return_value = []

        resp = client.post(
            "/api/v2/image-candidates/bulk-reject",
            json={"image_ids": [IMG_ID_1], "reviewer_id": REVIEWER},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["results"][0]["status"] == "skipped"
        mock_db.insert_image_metric_confirmations.assert_not_called()
        mock_db.skip_image_candidate_v2.assert_not_called()


# =============================================================================
# bulk-undo tests
# =============================================================================


class TestBulkUndoImageCandidates:
    def test_success_unskip_skipped_image(self, client, monkeypatch):
        """Skipped images are unskipped."""
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        mock_db.get_image_review_candidate_v2.return_value = _make_candidate(
            IMG_ID_1, review_status="skipped"
        )
        mock_db.unskip_image_candidate_v2.return_value = True
        mock_db.get_pending_image_candidates_v2.return_value = []

        resp = client.post(
            "/api/v2/image-candidates/bulk-undo",
            json={"image_ids": [IMG_ID_1], "reviewer_id": REVIEWER},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["results"][0]["status"] == "unskipped"
        mock_db.unskip_image_candidate_v2.assert_called_once_with(IMG_ID_1)

    def test_success_delete_confirmations_on_reviewed_image(self, client, monkeypatch):
        """Reviewed (non-skipped) images: all reviewer's confirmations are deleted."""
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        conf_id_1 = "conf-uuid-0001-0001-0001-000000000001"
        conf_id_2 = "conf-uuid-0001-0001-0001-000000000002"
        mock_db.get_image_review_candidate_v2.return_value = _make_candidate(
            IMG_ID_1, review_status="pending"
        )
        mock_db.get_image_metric_confirmations.return_value = [
            {"confirmation_id": conf_id_1, "reviewer_id": REVIEWER, "decision": "reject"},
            {"confirmation_id": conf_id_2, "reviewer_id": "other_reviewer", "decision": "accept"},
        ]
        mock_db.delete_image_metric_confirmation.return_value = {"confirmation_id": conf_id_1}
        mock_db.get_pending_image_candidates_v2.return_value = []

        resp = client.post(
            "/api/v2/image-candidates/bulk-undo",
            json={"image_ids": [IMG_ID_1], "reviewer_id": REVIEWER},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        result = body["results"][0]
        assert result["status"] == "undone"
        assert result["deleted_confirmations"] == 1
        # Only the reviewer's own confirmation is deleted
        mock_db.delete_image_metric_confirmation.assert_called_once_with(conf_id_1, REVIEWER)

    def test_missing_reviewer_id_returns_403(self, client, monkeypatch):
        mock_db = MagicMock()
        _patch_get_db(monkeypatch, mock_db)

        resp = client.post(
            "/api/v2/image-candidates/bulk-undo",
            json={"image_ids": [IMG_ID_1]},
        )

        assert resp.status_code == 403
        body = resp.get_json()
        assert body["error"] == "reviewer_name_required"
