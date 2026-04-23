"""Integration tests for the image-metric-confirmation API (#86 PR 3).

Covers the two new endpoints added by the chart-presence pivot:
- GET /api/v2/metrics/list — metric picker source
- POST /api/v2/image-metric-confirmations — per-metric reviewer decisions

Requires `TEST_DATABASE_URL`; skips otherwise. Exercises the full
DB round-trip through `insert_image_metric_confirmations` /
`get_image_metric_confirmations`.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.web.app import close_pool, create_app  # noqa: E402
from tests.integration.conftest import create_test_company_and_filing  # noqa: E402

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
            "API_KEY_REQUIRED": False,
        },
    )
    yield app
    close_pool(app)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_image(db_adapter: DatabaseAdapter) -> str:
    """Insert one v2_image_assets row with detected_metrics; return img_id."""
    _, filing_id = create_test_company_and_filing(
        db_adapter,
        cik="0009993201",
        accession_number="0009993201-24-000001",
        form_type="S-1",
    )
    img_id = str(uuid.uuid4())
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO v2_image_assets (
                    img_id, doc_id, filename, classification, processed,
                    detected_metrics
                ) VALUES (
                    %(img_id)s, %(doc_id)s, 'chart_test.png', 'chart', true,
                    %(detected)s::jsonb
                )
                """,
                {
                    "img_id": img_id,
                    "doc_id": filing_id,
                    "detected": '[{"metric_id":"cm_revenue_by_cohort","score":0.92}]',
                },
            )
    yield img_id
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM v2_image_metric_confirmations WHERE img_id = %s",
                (img_id,),
            )
            cur.execute("DELETE FROM v2_image_assets WHERE img_id = %s", (img_id,))


class TestMetricsList:
    def test_returns_metric_list(self, client):
        resp = client.get("/api/v2/metrics/list")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert isinstance(payload, list)
        assert len(payload) > 0
        first = payload[0]
        assert "metric_id" in first
        assert "display_name" in first
        assert "tier" in first


class TestImageMetricConfirmationsPost:
    def _post(self, client, body):
        return client.post("/api/v2/image-metric-confirmations", json=body)

    def test_accept_round_trip(self, client, db_adapter, seeded_image):
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "reviewer-1",
                "decisions": [
                    {"detected_metric_id": "cm_revenue_by_cohort", "decision": "accept"},
                ],
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        payload = resp.get_json()
        assert payload["ok"] is True
        assert payload["upserted"] == 1
        assert any(
            c["decision"] == "accept" and c["detected_metric_id"] == "cm_revenue_by_cohort"
            for c in payload["confirmations"]
        )

    def test_reject_requires_reason(self, client, seeded_image):
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "reviewer-1",
                "decisions": [
                    {"detected_metric_id": "cm_revenue_by_cohort", "decision": "reject"},
                ],
            },
        )
        assert resp.status_code == 400

    def test_correct_requires_different_ids(self, client, seeded_image):
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "reviewer-1",
                "decisions": [
                    {
                        "detected_metric_id": "cm_revenue_by_cohort",
                        "confirmed_metric_id": "cm_revenue_by_cohort",
                        "decision": "correct",
                    },
                ],
            },
        )
        assert resp.status_code == 400

    def test_add_round_trip(self, client, db_adapter, seeded_image):
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "reviewer-2",
                "decisions": [
                    {
                        "decision": "add",
                        "confirmed_metric_id": "cm_customer_retention_rate",
                    },
                ],
            },
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["upserted"] == 1
        added = [c for c in payload["confirmations"] if c["decision"] == "add"]
        assert len(added) == 1
        assert added[0]["confirmed_metric_id"] == "cm_customer_retention_rate"

    def test_invalid_img_id_rejected(self, client):
        resp = self._post(
            client,
            {
                "img_id": "not-a-uuid",
                "reviewer_id": "r",
                "decisions": [
                    {"detected_metric_id": "cm_revenue_by_cohort", "decision": "accept"},
                ],
            },
        )
        assert resp.status_code == 400
