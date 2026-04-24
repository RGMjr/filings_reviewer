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
# POST /ingest/preview — validation error re-renders form with preserved state
# ---------------------------------------------------------------------------


def test_ingest_preview_no_criteria_returns_400_with_preserved_state(client):
    """Missing industry/SIC/company → 400, form re-rendered with typed values preserved."""
    resp = client.post(
        "/ingest/preview",
        data={
            "year": "2023",
            "reviewer_name": "Rob",
            # No industries / SIC / company — triggers the validation error.
            # Keep a non-default form_types checkbox to prove checkbox state
            # survives the round-trip.
            "form_types": ["10k"],
        },
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    # Flash message rendered
    assert "industry, SIC code, or company name" in body
    # Year field repopulated
    assert 'value="2023"' in body
    # Reviewer name repopulated
    assert 'value="Rob"' in body

    # The 10-K checkbox is checked; the default s1f1 is not. The template
    # renders <input ... id="ft_X" ... {% if ... %}checked{% endif %}>; split
    # the HTML on `<input` so each chunk is a single input tag.
    def _input_block(html: str, input_id: str) -> str:
        for chunk in html.split("<input"):
            if f'id="{input_id}"' in chunk:
                return chunk.split(">", 1)[0]
        raise AssertionError(f"no <input id={input_id!r}> in response body")

    assert "checked" in _input_block(body, "ft_10k")
    assert "checked" not in _input_block(body, "ft_s1f1")


def test_ingest_preview_preserves_sic_and_company_on_error(client):
    """Typed-but-invalid SIC triggers ValueError; other fields still round-trip."""
    resp = client.post(
        "/ingest/preview",
        data={
            "year": "2023",
            "reviewer_name": "Rob",
            "sic_codes": "73AB",  # invalid → ValueError from resolve_criteria
            "company_name_ilike": "Chewy",
        },
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    # Typed SIC preserved verbatim so the user can fix the typo
    assert 'value="73AB"' in body
    # Company name preserved
    assert 'value="Chewy"' in body


def test_ingest_preview_company_only_passes_validation(client):
    """Company name alone (no industry/SIC) satisfies validation and reaches discover()."""
    from src.universe.onboarding import DiscoveryResult

    mock_db = MagicMock()

    with (
        patch("src.web.routes.ingest.get_db", return_value=mock_db),
        patch(
            "src.web.routes.ingest.discover",
            return_value=DiscoveryResult(new=[], already_extracted=[], gaps=[]),
        ),
    ):
        resp = client.post(
            "/ingest/preview",
            data={
                "year": "2023",
                "reviewer_name": "Rob",
                "company_name_ilike": "Chewy",
            },
        )
    # Success renders the preview template — confirm we didn't get the form
    # re-render 400.
    assert resp.status_code == 200


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
# Selective inclusion — only filing_ids submitted via checkbox reach the batch
# ---------------------------------------------------------------------------


def test_ingest_start_creates_batch_row_per_submitted_filing_id(client):
    """Only the filing_ids that were submitted (checkbox-checked) get batch rows.

    Regression test for the bug where the preview template always emitted a
    hidden filing_id per candidate, so users who intended to pick one filing
    ingested every candidate in the preview list.
    """
    form_data = {
        # Only 1 filing submitted — simulates user unchecking 3 of 4 candidates
        "filing_id": ["1748"],
        "bucket_1748": "new",
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
    }
    mock_db = _make_db_mock(batch_id="bbbbbbbb-cccc-dddd-eeee-000000000001")

    # Capture per-filing INSERTs into v2_ingest_batch_filings.
    mock_cur = mock_db.transaction.return_value.__enter__.return_value.cursor.return_value
    executed_sql: list[str] = []

    def _record(sql, params=None):
        executed_sql.append(str(sql))
        return None

    mock_cur.execute.side_effect = _record

    with patch("src.web.routes.ingest.get_db", return_value=mock_db):
        resp = client.post("/ingest/start", data=form_data)

    assert resp.status_code == 302
    per_filing_inserts = [s for s in executed_sql if "v2_ingest_batch_filings" in s]
    assert len(per_filing_inserts) == 1, (
        f"expected 1 filing row, got {len(per_filing_inserts)} — batch ingested unchecked candidates"
    )


def test_ingest_start_derives_reextract_from_bucket(client):
    """bucket=reextract on a submitted filing implies reextract_decisions[fid]=True.

    The preview template dropped the redundant per-row reextract checkbox —
    inclusion of an already-extracted filing now implies re-extraction,
    derived from the bucket classification.
    """
    form_data = {
        "filing_id": ["99"],
        "bucket_99": "reextract",  # user checked an already-extracted filing
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
        # No reextract_99 field — the template no longer emits one
    }
    mock_db = _make_db_mock()
    with patch("src.web.routes.ingest.get_db", return_value=mock_db):
        resp = client.post("/ingest/start", data=form_data)
    # Proceeds to batch creation — bucket-derived reextract is sufficient.
    assert resp.status_code == 302
    assert "/ingest/batch/" in resp.headers["Location"]


def test_ingest_start_bucket_reextract_reviewed_without_ack_still_blocked(client):
    """bucket=reextract_reviewed + submitted filing_id requires the ack checkbox.

    Derived-from-bucket re-extract must not bypass the reviewed-filing guard.
    """
    form_data = {
        "filing_id": ["42"],
        "bucket_42": "reextract_reviewed",
        "reviewer_name": "Rob",
        "criteria_json": json.dumps({"year": "2023", "sic_codes": "7372"}),
        "resolved_json": json.dumps({}),
        # reextract_reviewed_ack intentionally omitted
        # No reextract_42 — new template doesn't emit it
    }
    resp = client.post("/ingest/start", data=form_data)
    assert resp.status_code == 400


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


# ---------------------------------------------------------------------------
# POST /ingest/populate — XHR inline flow
# ---------------------------------------------------------------------------


def test_populate_xhr_returns_json_batch_id(client):
    """POST /ingest/populate with XHR header returns JSON {batch_id: ...} 202."""
    mock_db = _make_db_mock(batch_id="cccccccc-dddd-eeee-ffff-111111111111")
    with patch("src.web.routes.ingest.get_db", return_value=mock_db):
        resp = client.post(
            "/ingest/populate",
            data={
                "reviewer_name": "Rob",
                "year": "2023",
                "form_type": "s1f1",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body is not None
    assert "batch_id" in body
    assert body["batch_id"] == "cccccccc-dddd-eeee-ffff-111111111111"


def test_populate_xhr_missing_reviewer_returns_json_error(client):
    """POST /ingest/populate XHR without reviewer_name returns JSON 400."""
    resp = client.post(
        "/ingest/populate",
        data={"year": "2023", "form_type": "s1f1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert "error" in body


def test_populate_xhr_invalid_form_type_returns_json_error(client):
    """POST /ingest/populate XHR with unknown form_type returns JSON 400."""
    resp = client.post(
        "/ingest/populate",
        data={"reviewer_name": "Rob", "year": "2023", "form_type": "bogus"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert "error" in body


def test_populate_non_xhr_still_redirects(client):
    """POST /ingest/populate without XHR header still redirects (302)."""
    mock_db = _make_db_mock(batch_id="dddddddd-eeee-ffff-0000-222222222222")
    with patch("src.web.routes.ingest.get_db", return_value=mock_db):
        resp = client.post(
            "/ingest/populate",
            data={
                "reviewer_name": "Rob",
                "year": "2023",
                "form_type": "s1f1",
            },
        )
    assert resp.status_code == 302
    assert "/ingest/batch/" in resp.headers["Location"]


def test_ingest_preview_template_has_gap_banner_id(client):
    """Rendered ingest_preview.html includes id='gap-banner' and gap-populate-form class."""
    from src.universe.onboarding import DiscoveryResult

    class _Gap:
        year = 2023
        form_type = "s1f1"

    mock_db = MagicMock()
    with (
        patch("src.web.routes.ingest.get_db", return_value=mock_db),
        patch(
            "src.web.routes.ingest.discover",
            return_value=DiscoveryResult(new=[], already_extracted=[], gaps=[_Gap()]),
        ),
    ):
        resp = client.post(
            "/ingest/preview",
            data={"reviewer_name": "Rob", "company_name_ilike": "Acme"},
        )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="gap-banner"' in body
    assert "gap-populate-form" in body


def test_ingest_preview_template_has_section_ids(client):
    """Rendered ingest_preview.html includes the three section wrapper IDs."""
    from src.universe.onboarding import DiscoveryResult

    mock_db = MagicMock()
    with (
        patch("src.web.routes.ingest.get_db", return_value=mock_db),
        patch(
            "src.web.routes.ingest.discover",
            return_value=DiscoveryResult(new=[], already_extracted=[], gaps=[]),
        ),
    ):
        resp = client.post(
            "/ingest/preview",
            data={"reviewer_name": "Rob", "company_name_ilike": "Acme"},
        )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="section-new"' in body
    assert 'id="section-no-review"' in body
    assert 'id="section-reviewed"' in body
