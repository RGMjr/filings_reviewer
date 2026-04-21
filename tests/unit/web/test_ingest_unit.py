"""
Unit tests for the ingest blueprint — no DB required.

Covers:
- Form-field parsing (_parse_form_criteria)
- Volume-band server-side enforcement (HARD_WARN requires ack; REFINE/BLOCK rejected)
- Reviewed-filing confirmation gating
- url_for resolution for all new ingest endpoints (covered by test_url_for_resolves.py)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.universe.onboarding import VolumeBand
from src.web.app import create_app

# ---------------------------------------------------------------------------
# App fixture (no DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    application = create_app("testing")
    application.config["TESTING"] = True
    application.config["DATABASE_URL"] = "postgresql://test"
    application.config["_db_pool"] = None
    application.config["INGEST_SPAWN_SUBPROCESS"] = False
    return application


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_mock(batch_id="aaaaaaaa-bbbb-cccc-dddd-000000000000"):
    """Return a mock DatabaseAdapter that simulates a successful batch insert."""
    mock_db = MagicMock()

    # transaction() is a context manager that yields a psycopg connection
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"batch_id": batch_id}
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur

    # db.transaction() returns context manager that yields mock_conn
    mock_tx_cm = MagicMock()
    mock_tx_cm.__enter__ = MagicMock(return_value=mock_conn)
    mock_tx_cm.__exit__ = MagicMock(return_value=False)
    mock_db.transaction.return_value = mock_tx_cm

    return mock_db


# ---------------------------------------------------------------------------
# GET /ingest/ — renders form
# ---------------------------------------------------------------------------


def test_ingest_form_get(client):
    """GET /ingest/ returns 200 and renders form."""
    resp = client.get("/ingest/")
    assert resp.status_code == 200
    assert b"Preview Candidates" in resp.data
    assert b"reviewer_name" in resp.data


def test_ingest_form_pre_fills_reviewer_cookie(client):
    """GET /ingest/ pre-fills reviewer name from cookie."""
    client.set_cookie("ingest_reviewer", "TestUser")
    resp = client.get("/ingest/")
    assert resp.status_code == 200
    assert b"TestUser" in resp.data


# ---------------------------------------------------------------------------
# _parse_form_criteria helper
# ---------------------------------------------------------------------------


def test_parse_form_criteria_defaults(app):
    """_parse_form_criteria returns form_types=['s1f1'] when none selected."""
    from src.web.routes.ingest import _parse_form_criteria

    with app.test_request_context(
        "/ingest/preview",
        method="POST",
        data={
            "year": "2023",
            "reviewer_name": "Rob",
        },
    ):
        result = _parse_form_criteria()
    assert result["form_types"] == ["s1f1"]
    assert result["year"] == "2023"
    assert result["_reviewer_name"] == "Rob"


def test_parse_form_criteria_multi_industry(app):
    """_parse_form_criteria captures multiple industries."""
    from src.web.routes.ingest import _parse_form_criteria

    with app.test_request_context(
        "/ingest/preview",
        method="POST",
        data={
            "industries": ["software", "grocery_retail"],
            "year": "2022",
            "reviewer_name": "Alice",
        },
    ):
        result = _parse_form_criteria()
    assert "software" in result["industries"]
    assert "grocery_retail" in result["industries"]


# ---------------------------------------------------------------------------
# Volume band enforcement
# ---------------------------------------------------------------------------


def test_ingest_start_refine_returns_400(client):
    """POST /ingest/start with REFINE volume (500+ filings) returns 400."""
    # 500 filing IDs triggers REFINE band
    filing_ids = [str(i) for i in range(1, 501)]
    form_data = {
        "filing_id": filing_ids,
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
    }
    resp = client.post("/ingest/start", data=form_data)
    assert resp.status_code == 400


def test_ingest_start_block_returns_400(client):
    """POST /ingest/start with BLOCK volume (1000+ filings) returns 400."""
    filing_ids = [str(i) for i in range(1, 1001)]
    form_data = {
        "filing_id": filing_ids,
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
    }
    resp = client.post("/ingest/start", data=form_data)
    assert resp.status_code == 400


def test_ingest_start_hard_warn_without_ack_returns_400(client):
    """POST /ingest/start with HARD_WARN volume but no hard_warn_ack returns 400."""
    # 200 filings triggers HARD_WARN
    filing_ids = [str(i) for i in range(1, 201)]
    form_data = {
        "filing_id": filing_ids,
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
        # hard_warn_ack intentionally omitted
    }
    resp = client.post("/ingest/start", data=form_data)
    assert resp.status_code == 400


def test_ingest_start_hard_warn_with_ack_proceeds(client):
    """POST /ingest/start with HARD_WARN volume + ack proceeds (mocked DB)."""
    filing_ids = [str(i) for i in range(1, 201)]
    form_data = {
        "filing_id": filing_ids,
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
        "hard_warn_ack": "on",
    }
    mock_db = _make_db_mock()
    with patch("src.web.routes.ingest.get_db", return_value=mock_db):
        resp = client.post("/ingest/start", data=form_data)
    # Should redirect (302) to batch page
    assert resp.status_code == 302
    assert "/ingest/batch/" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Reviewed-filing confirmation gating
# ---------------------------------------------------------------------------


def test_ingest_start_reviewed_filing_without_ack_returns_400(client):
    """POST /ingest/start: reviewed filing checkbox set but no reextract_reviewed_ack → 400."""
    form_data = {
        "filing_id": ["42"],
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
        "reextract_42": "on",
        "bucket_42": "reextract_reviewed",
        # reextract_reviewed_ack intentionally omitted
    }
    resp = client.post("/ingest/start", data=form_data)
    assert resp.status_code == 400


def test_ingest_start_reviewed_filing_with_ack_proceeds(client):
    """POST /ingest/start: reviewed filing checkbox set with ack proceeds (mocked DB)."""
    form_data = {
        "filing_id": ["42"],
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
        "reextract_42": "on",
        "bucket_42": "reextract_reviewed",
        "reextract_reviewed_ack": "on",
    }
    mock_db = _make_db_mock()
    with patch("src.web.routes.ingest.get_db", return_value=mock_db):
        resp = client.post("/ingest/start", data=form_data)
    assert resp.status_code == 302
    assert "/ingest/batch/" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Missing fields
# ---------------------------------------------------------------------------


def test_ingest_start_no_filing_ids_returns_400(client):
    """POST /ingest/start with no filing_ids returns 400."""
    resp = client.post(
        "/ingest/start",
        data={
            "reviewer_name": "Rob",
            "criteria_json": "{}",
            "resolved_json": "{}",
        },
    )
    assert resp.status_code == 400


def test_ingest_start_no_reviewer_name_returns_400(client):
    """POST /ingest/start with no reviewer_name returns 400."""
    resp = client.post(
        "/ingest/start",
        data={
            "filing_id": ["1"],
            "reviewer_name": "",
            "criteria_json": "{}",
            "resolved_json": "{}",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Volume band helpers
# ---------------------------------------------------------------------------


def test_volume_band_alert_class():
    """_volume_band_alert_class returns correct Bootstrap alert class."""
    from src.web.routes.ingest import _volume_band_alert_class

    assert _volume_band_alert_class(VolumeBand.OK) == "alert-success"
    assert _volume_band_alert_class(VolumeBand.SOFT_WARN) == "alert-warning"
    assert _volume_band_alert_class(VolumeBand.HARD_WARN) == "alert-warning"
    assert _volume_band_alert_class(VolumeBand.REFINE) == "alert-danger"
    assert _volume_band_alert_class(VolumeBand.BLOCK) == "alert-danger"
