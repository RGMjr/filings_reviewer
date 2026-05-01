"""Unit tests for Phase-4a reviewer_notes round-trip on image confirmations.

Covers the validation gate (max 1000 chars, must be string) and verifies the
field is forwarded to db.insert_image_metric_confirmations. Bulk-reject path
is exercised separately to confirm it defaults reviewer_notes to None (no
free-text capture on bulk actions, by design).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


@pytest.fixture
def app():
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
        # The endpoint hits a few methods after upsert; stub the minimum that
        # keeps the success path from blowing up.
        db.insert_image_metric_confirmations.return_value = 1
        db.get_image_metric_confirmations.return_value = []
        db.get_image_review_candidates_for_filing_v2.return_value = []
        db.insert_audit_log.return_value = None
        mock_get_db.return_value = db
        yield db


_ENDPOINT = "/api/v2/image-metric-confirmations"


def _accept_payload(notes: str | None = None) -> dict:
    """A minimal valid 'accept' decision payload."""
    decision = {
        "detected_metric_id": "cm_total_customers",
        "decision": "accept",
    }
    if notes is not None:
        decision["reviewer_notes"] = notes
    return {
        "img_id": "00000000-0000-0000-0000-000000000001",
        "reviewer_id": "RGM",
        "decisions": [decision],
    }


class TestReviewerNotesValidation:
    def test_notes_omitted_persists_as_none(self, client, mock_db):
        resp = client.post(_ENDPOINT, json=_accept_payload(notes=None))
        assert resp.status_code == 200
        # Forwarded shape: db received a single decision with reviewer_notes=None.
        mock_db.insert_image_metric_confirmations.assert_called_once()
        args = mock_db.insert_image_metric_confirmations.call_args.args
        decisions = args[1]
        assert decisions[0]["reviewer_notes"] is None

    def test_notes_string_persists_verbatim(self, client, mock_db):
        resp = client.post(_ENDPOINT, json=_accept_payload(notes="values appear to be dates"))
        assert resp.status_code == 200
        decisions = mock_db.insert_image_metric_confirmations.call_args.args[1]
        assert decisions[0]["reviewer_notes"] == "values appear to be dates"

    def test_notes_empty_string_normalizes_to_none(self, client, mock_db):
        # Whitespace-only / empty strings should NOT pollute the column with
        # empty rows; treat them as None.
        resp = client.post(_ENDPOINT, json=_accept_payload(notes=""))
        assert resp.status_code == 200
        decisions = mock_db.insert_image_metric_confirmations.call_args.args[1]
        assert decisions[0]["reviewer_notes"] is None

    def test_notes_over_1000_chars_returns_400(self, client, mock_db):
        long = "x" * 1001
        resp = client.post(_ENDPOINT, json=_accept_payload(notes=long))
        assert resp.status_code == 400
        body = resp.get_json()
        assert "1000 characters or less" in body["error"]
        mock_db.insert_image_metric_confirmations.assert_not_called()

    def test_notes_at_1000_chars_succeeds(self, client, mock_db):
        # Boundary check — exactly at the limit must pass.
        boundary = "x" * 1000
        resp = client.post(_ENDPOINT, json=_accept_payload(notes=boundary))
        assert resp.status_code == 200
        decisions = mock_db.insert_image_metric_confirmations.call_args.args[1]
        assert len(decisions[0]["reviewer_notes"]) == 1000

    def test_notes_non_string_returns_400(self, client, mock_db):
        resp = client.post(_ENDPOINT, json=_accept_payload(notes=42))
        assert resp.status_code == 400
        body = resp.get_json()
        assert "must be a string" in body["error"]
        mock_db.insert_image_metric_confirmations.assert_not_called()
