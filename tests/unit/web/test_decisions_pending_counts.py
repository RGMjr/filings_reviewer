"""gh-320: POST /api/v2/decisions must return fresh pending counts.

The stale IMAGE_PENDING page-load constant caused spurious redirects to the
images tab after clearing all images then deciding the last text fact.  The
fix adds image_pending_count + text_pending_count to the decisions response so
the JS cascade can refresh before checking whether images remain.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app
from src.web.routes.api_unified import _get_filing_pending_counts  # noqa: F401

# ---------------------------------------------------------------------------
# Unit test for the helper
# ---------------------------------------------------------------------------


def test_get_filing_pending_counts_counts_correctly():
    db = MagicMock()
    db.get_v2_facts_for_filing.return_value = [{"fact_id": "a"}, {"fact_id": "b"}]
    db.get_image_review_candidates_for_filing_v2.return_value = [
        {"img_id": "x", "image_review_state": "pending"},
        {"img_id": "y", "image_review_state": "relevant"},
        {"img_id": "z", "image_review_state": "no_relevant"},
    ]
    result = _get_filing_pending_counts(db, filing_id=42)
    assert result == {"text_pending_count": 2, "image_pending_count": 1}
    db.get_v2_facts_for_filing.assert_called_once_with(42, status="pending_review")


def test_get_filing_pending_counts_zero_when_all_done():
    db = MagicMock()
    db.get_v2_facts_for_filing.return_value = []
    db.get_image_review_candidates_for_filing_v2.return_value = [
        {"img_id": "x", "image_review_state": "relevant"},
    ]
    result = _get_filing_pending_counts(db, filing_id=1)
    assert result == {"text_pending_count": 0, "image_pending_count": 0}


# ---------------------------------------------------------------------------
# Integration: pending counts appear in POST /api/v2/decisions response
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    return create_app(
        config_name="testing",
        config_override={"DATABASE_URL": "postgresql://test:test@localhost/test"},
    )


@pytest.fixture()
def client(app):
    return app.test_client()


def _mock_db(*, text_remaining: int = 0, image_remaining: int = 0) -> MagicMock:
    fact_id = str(uuid.uuid4())
    db = MagicMock()
    db.insert_audit_log.return_value = None
    db.get_v2_fact_by_id.return_value = {
        "fact_id": fact_id,
        "filing_id": 1,
        "decision_id": None,
        "review_status": "pending_review",
    }
    db.insert_v2_review_decision.return_value = str(uuid.uuid4())
    # _get_next_pending_fact: no next fact (last one in the view)
    db.get_v2_facts_for_filing.return_value = []
    # _get_filing_pending_counts: image candidates
    db.get_image_review_candidates_for_filing_v2.return_value = [
        {"img_id": str(uuid.uuid4()), "image_review_state": "pending"}
        for _ in range(image_remaining)
    ]
    return db, fact_id


def test_decisions_response_includes_pending_counts_when_no_images_remain(client):
    db, fact_id = _mock_db(text_remaining=0, image_remaining=0)
    with patch("src.web.routes.api_unified.get_db", return_value=db):
        resp = client.post(
            "/api/v2/decisions",
            json={
                "fact_id": fact_id,
                "decision": "accept",
                "reviewer_id": "RGM",
            },
            headers={"Referer": "http://localhost/v2/review/1"},
        )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["image_pending_count"] == 0
    assert data["text_pending_count"] == 0


def test_decisions_response_includes_pending_counts_when_images_remain(client):
    db, fact_id = _mock_db(text_remaining=0, image_remaining=2)
    with patch("src.web.routes.api_unified.get_db", return_value=db):
        resp = client.post(
            "/api/v2/decisions",
            json={
                "fact_id": fact_id,
                "decision": "accept",
                "reviewer_id": "RGM",
            },
            headers={"Referer": "http://localhost/v2/review/1"},
        )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["image_pending_count"] == 2
    assert data["text_pending_count"] == 0
