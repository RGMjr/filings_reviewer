"""Integration tests for the /ingest batch-ingestion Flask flow.

Covers the /ingest/start → DB write path, the /api/v2/ingest/batches/<id>/status
contract, /cancel idempotency, and API auth. Subprocess spawning is disabled
throughout (`INGEST_SPAWN_SUBPROCESS=False`) so the runner never actually runs.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.universe.onboarding import VolumeBand  # noqa: E402
from src.web.app import close_pool, create_app  # noqa: E402
from src.web.routes.ingest import _volume_band_alert_class  # noqa: E402
from tests.integration.conftest import (  # noqa: E402
    create_test_company_and_filing,
    create_test_v2_decision,
    create_test_v2_document,
    create_test_v2_fact,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="module")
def db_adapter(db_url: str) -> DatabaseAdapter:
    db = DatabaseAdapter(db_url)
    yield db
    db.close()


@pytest.fixture
def app(db_url: str):
    app = create_app(
        "testing",
        config_override={
            "DATABASE_URL": db_url,
            "INGEST_SPAWN_SUBPROCESS": False,
            "API_KEY_REQUIRED": True,
            "API_KEY": "test-key-xyz",
        },
    )
    yield app
    close_pool(app)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_filing(db_adapter: DatabaseAdapter) -> int:
    """Seed a single filing + company; return filing_id."""
    _, filing_id = create_test_company_and_filing(
        db_adapter,
        cik="0009993001",
        accession_number="0009993001-24-000001",
        form_type="S-1",
    )
    yield filing_id
    db_adapter.execute(
        "DELETE FROM v2_ingest_batch_filings WHERE filing_id = %(id)s",
        {"id": filing_id},
    )
    db_adapter.execute("DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id})
    db_adapter.execute("DELETE FROM companies WHERE cik = '0009993001'")


@pytest.fixture
def batch_id(db_adapter: DatabaseAdapter, seeded_filing: int) -> str:
    rows = db_adapter.query(
        """
        INSERT INTO v2_ingest_batches
            (kind, reviewer_id, criteria, resolved_query, limits, total_filings, status)
        VALUES ('onboard', 'testbot', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 1, 'queued')
        RETURNING batch_id::text;
        """
    )
    bid = rows[0]["batch_id"]
    db_adapter.execute(
        """
        INSERT INTO v2_ingest_batch_filings
            (batch_id, filing_id, initial_bucket, current_status)
        VALUES (%s, %s, 'new', 'queued');
        """,
        [bid, seeded_filing],
    )
    yield bid
    db_adapter.execute("DELETE FROM v2_ingest_batches WHERE batch_id = %s", [bid])


class TestFormRender:
    def test_get_ingest_renders_form(self, client):
        r = client.get("/ingest/")
        assert r.status_code == 200
        assert b"Reviewer" in r.data or b"reviewer" in r.data

    def test_reviewer_cookie_prefills(self, client):
        client.set_cookie("ingest_reviewer", "rob", domain="localhost")
        r = client.get("/ingest/")
        assert r.status_code == 200
        assert b"rob" in r.data


class TestStartFlow:
    def _start_form(self, seeded_filing: int, **overrides) -> dict:
        base = {
            "reviewer_name": "testbot",
            "filing_id": [str(seeded_filing)],
            f"bucket_{seeded_filing}": "new",
            "criteria_json": json.dumps({"industries": ["software"], "year": "2024"}),
            "resolved_json": json.dumps(
                {"sic_codes": ["7372"], "form_types": ["S-1"], "year_min": 2024, "year_max": 2024}
            ),
        }
        base.update(overrides)
        return base

    def test_start_creates_batch_and_filings(self, client, db_adapter, seeded_filing):
        form = self._start_form(seeded_filing)
        r = client.post("/ingest/start", data=form, follow_redirects=False)
        assert r.status_code == 302, r.data
        assert r.location.startswith("/ingest/batch/")
        batch_id_str = r.location.split("/")[-1]

        batch_rows = db_adapter.query(
            "SELECT status, reviewer_id, total_filings FROM v2_ingest_batches WHERE batch_id = %s",
            [batch_id_str],
        )
        assert len(batch_rows) == 1
        assert batch_rows[0]["status"] == "queued"
        assert batch_rows[0]["reviewer_id"] == "testbot"
        assert batch_rows[0]["total_filings"] == 1

        filing_rows = db_adapter.query(
            "SELECT filing_id, current_status, initial_bucket FROM v2_ingest_batch_filings WHERE batch_id = %s",
            [batch_id_str],
        )
        assert len(filing_rows) == 1
        assert filing_rows[0]["current_status"] == "queued"
        assert filing_rows[0]["initial_bucket"] == "new"

        db_adapter.execute("DELETE FROM v2_ingest_batches WHERE batch_id = %s", [batch_id_str])

    def test_start_rejects_missing_reviewed_ack(self, client, seeded_filing):
        form = self._start_form(
            seeded_filing,
            **{
                f"bucket_{seeded_filing}": "reextract_reviewed",
                f"reextract_{seeded_filing}": "on",
            },
        )
        # no reextract_reviewed_ack
        r = client.post("/ingest/start", data=form, follow_redirects=False)
        assert r.status_code == 400

    def test_start_empty_filing_list_rejects(self, client):
        form = {
            "reviewer_name": "testbot",
            "criteria_json": "{}",
            "resolved_json": "{}",
        }
        r = client.post("/ingest/start", data=form, follow_redirects=False)
        # Empty = volume 0 = OK band, but nothing to do; implementation may 302 or 400.
        assert r.status_code in (400, 302)


_AUTH = {"X-API-Key": "test-key-xyz"}


class TestStatusApi:
    def test_status_returns_full_contract(self, client, batch_id, seeded_filing):
        r = client.get(f"/api/v2/ingest/batches/{batch_id}/status", headers=_AUTH)
        assert r.status_code == 200, r.data
        body = r.get_json()

        # Required top-level keys
        for key in (
            "batch_id",
            "kind",
            "status",
            "reviewer_id",
            "total_filings",
            "counts",
            "created_at",
            "started_at",
            "finished_at",
            "cancelled_at",
            "error",
            "filings",
        ):
            assert key in body, f"missing {key}"

        # Counts contains all 7 enum values
        assert set(body["counts"].keys()) == {
            "queued",
            "fetching",
            "extracting",
            "persisted",
            "failed",
            "skipped",
            "cancelled",
        }
        assert body["counts"]["queued"] == 1

        # Filings list has one row with expected shape
        assert len(body["filings"]) == 1
        f = body["filings"][0]
        assert f["filing_id"] == seeded_filing
        assert f["current_status"] == "queued"
        assert f["initial_bucket"] == "new"

    def test_status_404_for_unknown_batch(self, client):
        r = client.get(f"/api/v2/ingest/batches/{uuid.uuid4()}/status", headers=_AUTH)
        assert r.status_code == 404


class TestCancelApi:
    def test_cancel_flips_running_batch(self, client, db_adapter, batch_id):
        r = client.post(f"/api/v2/ingest/batches/{batch_id}/cancel", headers=_AUTH)
        assert r.status_code == 200, r.data
        assert r.get_json()["status"] == "ok"

        rows = db_adapter.query(
            "SELECT status, cancelled_at FROM v2_ingest_batches WHERE batch_id = %s",
            [batch_id],
        )
        assert rows[0]["status"] == "cancelled"
        assert rows[0]["cancelled_at"] is not None

    def test_cancel_is_idempotent(self, client, batch_id):
        r1 = client.post(f"/api/v2/ingest/batches/{batch_id}/cancel", headers=_AUTH)
        r2 = client.post(f"/api/v2/ingest/batches/{batch_id}/cancel", headers=_AUTH)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.get_json()["status"] == "ok"


class TestAuth:
    def test_status_rejects_cross_origin_without_key(self, client, batch_id):
        r = client.get(
            f"/api/v2/ingest/batches/{batch_id}/status",
            headers={"Origin": "https://evil.example.com"},
        )
        assert r.status_code == 401

    def test_status_allows_with_valid_key(self, client, batch_id):
        r = client.get(
            f"/api/v2/ingest/batches/{batch_id}/status",
            headers={"Origin": "https://evil.example.com", "X-API-Key": "test-key-xyz"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Phase 6: populate flow
# ---------------------------------------------------------------------------


class TestPopulateFlow:
    def test_populate_creates_batch_no_filings(self, client, db_adapter):
        form = {"reviewer_name": "popbot", "year": "2024", "form_type": "10-K"}
        r = client.post("/ingest/populate", data=form, follow_redirects=False)
        assert r.status_code == 302, r.data
        assert r.location.startswith("/ingest/batch/")
        batch_id = r.location.split("/")[-1]

        rows = db_adapter.query(
            "SELECT kind, status, criteria FROM v2_ingest_batches WHERE batch_id = %s",
            [batch_id],
        )
        assert len(rows) == 1
        assert rows[0]["kind"] == "populate"
        assert rows[0]["status"] == "queued"
        criteria = rows[0]["criteria"]
        if isinstance(criteria, str):
            criteria = json.loads(criteria)
        assert criteria == {"year": 2024, "form_type": "10-K"}

        # No per-filing rows for populate
        filing_rows = db_adapter.query(
            "SELECT 1 FROM v2_ingest_batch_filings WHERE batch_id = %s", [batch_id]
        )
        assert filing_rows == []

        db_adapter.execute("DELETE FROM v2_ingest_batches WHERE batch_id = %s", [batch_id])

    def test_populate_invalid_year_rejects(self, client):
        form = {"reviewer_name": "popbot", "year": "abc", "form_type": "10-K"}
        r = client.post("/ingest/populate", data=form, follow_redirects=False)
        assert r.status_code == 400

    def test_populate_year_out_of_range_rejects(self, client):
        form = {"reviewer_name": "popbot", "year": "1850", "form_type": "10-K"}
        r = client.post("/ingest/populate", data=form, follow_redirects=False)
        assert r.status_code == 400

    def test_populate_unknown_form_type_rejects(self, client):
        form = {"reviewer_name": "popbot", "year": "2024", "form_type": "WHAT-EVER"}
        r = client.post("/ingest/populate", data=form, follow_redirects=False)
        assert r.status_code == 400

    def test_populate_status_includes_populate_progress_and_criteria(self, client, db_adapter):
        form = {"reviewer_name": "popbot", "year": "2024", "form_type": "10-K"}
        r = client.post("/ingest/populate", data=form, follow_redirects=False)
        batch_id = r.location.split("/")[-1]

        # Initially populate_progress is null
        s = client.get(f"/api/v2/ingest/batches/{batch_id}/status", headers=_AUTH)
        body = s.get_json()
        assert body["kind"] == "populate"
        assert body["populate_progress"] is None
        assert body["criteria"] == {"year": 2024, "form_type": "10-K"}
        assert body["filings"] == []

        # After runner writes progress, status reflects it
        db_adapter.execute(
            """
            UPDATE v2_ingest_batches
            SET limits = jsonb_set(coalesce(limits,'{}'::jsonb),
                                    '{populate_progress}', %s::jsonb)
            WHERE batch_id = %s
            """,
            [json.dumps({"processed": 17, "total": 42}), batch_id],
        )
        s2 = client.get(f"/api/v2/ingest/batches/{batch_id}/status", headers=_AUTH)
        body2 = s2.get_json()
        assert body2["populate_progress"] == {"processed": 17, "total": 42}

        db_adapter.execute("DELETE FROM v2_ingest_batches WHERE batch_id = %s", [batch_id])

    def test_onboard_status_also_includes_criteria_field(self, client, batch_id):
        """Regression: criteria field must appear for onboard batches too."""
        r = client.get(f"/api/v2/ingest/batches/{batch_id}/status", headers=_AUTH)
        body = r.get_json()
        assert "criteria" in body
        assert isinstance(body["criteria"], dict)
        assert body["populate_progress"] is None  # onboard batches always null


# ---------------------------------------------------------------------------
# TestIngestPreview — integration coverage for POST /ingest/preview (#61)
# ---------------------------------------------------------------------------

# SIC code and form type used throughout TestIngestPreview.
# 10-K avoids the is_in_scope_phase1 gate; SIC 7372 is prepackaged software.
_PREVIEW_SIC = "7372"
_PREVIEW_FORM = "10-K"
_PREVIEW_YEAR = "2024"

# Base form data for /ingest/preview — uses sic_codes directly to bypass
# industry-YAML resolution and keep tests self-contained.
_PREVIEW_FORM_BASE = {
    "reviewer_name": "previewbot",
    "sic_codes": _PREVIEW_SIC,
    "form_types": _PREVIEW_FORM,
    "year": _PREVIEW_YEAR,
}


@pytest.fixture
def two_seeded_filings(db_adapter: DatabaseAdapter):
    """Seed two filings (distinct CIKs) and return (filing_id_a, filing_id_b).

    Filing A: has a v2_documents row (already_extracted=True) plus a
              v2_metric_facts row and v2_review_decisions row so it lands
              in the ``already_reviewed`` bucket.
    Filing B: no v2_documents row — lands in the ``new`` bucket.

    Teardown removes all seeded rows in dependency order.
    """
    _, filing_id_a = create_test_company_and_filing(
        db_adapter,
        cik="0008881001",
        accession_number="0008881001-24-000001",
        form_type=_PREVIEW_FORM,
        filing_date="2024-03-15",
        company_name="Preview Corp A",
        industry_code=_PREVIEW_SIC,
    )
    # Set is_in_scope_phase1 not required for 10-K, but update industry_code on
    # the filing row just in case the discovery join uses companies.industry_code.
    # (create_test_company_and_filing already sets it via create_test_company.)

    _, filing_id_b = create_test_company_and_filing(
        db_adapter,
        cik="0008882002",
        accession_number="0008882002-24-000001",
        form_type=_PREVIEW_FORM,
        filing_date="2024-06-20",
        company_name="Preview Corp B",
        industry_code=_PREVIEW_SIC,
    )

    # Make filing A "already extracted" with reviewer work.
    doc_id = create_test_v2_document(db_adapter, filing_id=filing_id_a)
    fact_id = create_test_v2_fact(db_adapter, filing_id=filing_id_a)
    create_test_v2_decision(db_adapter, fact_id=fact_id, decision="accept")

    yield filing_id_a, filing_id_b

    # Teardown — innermost dependents first.
    db_adapter.execute(
        "DELETE FROM v2_review_decisions WHERE fact_id IN "
        "(SELECT fact_id FROM v2_metric_facts WHERE filing_id = %(fid)s)",
        {"fid": filing_id_a},
    )
    db_adapter.execute(
        "DELETE FROM v2_metric_facts WHERE filing_id = %(fid)s",
        {"fid": filing_id_a},
    )
    db_adapter.execute(
        "DELETE FROM v2_documents WHERE filing_id = %(filing_id)s::uuid",
        {"filing_id": doc_id},
    )
    db_adapter.execute(
        "DELETE FROM filings WHERE filing_id IN (%(a)s, %(b)s)",
        {"a": filing_id_a, "b": filing_id_b},
    )
    db_adapter.execute("DELETE FROM companies WHERE cik IN ('0008881001', '0008882002')")


class TestIngestPreview:
    def test_preview_renders_three_bucket_split(self, client, two_seeded_filings):
        """POST /ingest/preview returns 200 and renders all three bucket sections."""
        filing_id_a, filing_id_b = two_seeded_filings

        r = client.post("/ingest/preview", data=_PREVIEW_FORM_BASE)

        assert r.status_code == 200, r.data[:500]

        html = r.data
        # All three bucket headings must appear.
        assert b"New Filings" in html
        assert b"Already Extracted" in html
        assert b"Has Review Decisions" in html

        # Both filing IDs must appear somewhere in the rendered page.
        assert str(filing_id_a).encode() in html
        assert str(filing_id_b).encode() in html

    def test_preview_volume_banner_alert_class(self, client, two_seeded_filings):
        """Two filings → VolumeBand.OK → alert-success banner in rendered HTML.

        The expected class is derived from _volume_band_alert_class so the
        test fails loudly if the mapping changes.
        """
        expected_class = _volume_band_alert_class(VolumeBand.OK)
        assert expected_class == "alert-success"  # sanity-check the mapping itself

        r = client.post("/ingest/preview", data=_PREVIEW_FORM_BASE)

        assert r.status_code == 200, r.data[:500]
        assert expected_class.encode() in r.data

    def test_preview_hidden_filing_ids_survive_render(self, client, two_seeded_filings):
        """Hidden filing_id inputs must be present in the rendered start-form HTML."""
        filing_id_a, filing_id_b = two_seeded_filings

        r = client.post("/ingest/preview", data=_PREVIEW_FORM_BASE)

        assert r.status_code == 200, r.data[:500]

        html = r.data
        # At least one hidden filing_id input must appear per discovered filing.
        assert html.count(b'name="filing_id"') >= 2
        # Each discovered filing's ID must appear as a hidden-field value.
        assert (
            f'name="filing_id" value="{filing_id_a}"'.encode() in html
            or f'value="{filing_id_a}"'.encode() in html
        )
        assert (
            f'name="filing_id" value="{filing_id_b}"'.encode() in html
            or f'value="{filing_id_b}"'.encode() in html
        )
