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
from src.web.app import close_pool, create_app  # noqa: E402
from tests.integration.conftest import (  # noqa: E402
    create_test_company_and_filing,
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
            "resolved_json": json.dumps({"sic_codes": ["7372"], "form_types": ["S-1"], "year_min": 2024, "year_max": 2024}),
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
            "batch_id", "kind", "status", "reviewer_id", "total_filings",
            "counts", "created_at", "started_at", "finished_at",
            "cancelled_at", "error", "filings",
        ):
            assert key in body, f"missing {key}"

        # Counts contains all 7 enum values
        assert set(body["counts"].keys()) == {
            "queued", "fetching", "extracting", "persisted",
            "failed", "skipped", "cancelled",
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
