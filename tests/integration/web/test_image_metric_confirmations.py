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
                    img_id, doc_id, filename, dom_locator, classification, processed,
                    detected_metrics
                ) VALUES (
                    %(img_id)s, %(doc_id)s, 'chart_test.png', '/html/body/img[1]',
                    'chart', true, %(detected)s::jsonb
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
            cur.execute(
                "DELETE FROM v2_metric_facts WHERE doc_id = %s AND source_type = 'chart'",
                (filing_id,),
            )


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

    def test_skip_round_trip(self, client, seeded_image):
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "reviewer-skip",
                "decisions": [
                    {"detected_metric_id": "cm_revenue_by_cohort", "decision": "skip"},
                ],
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        payload = resp.get_json()
        assert payload["upserted"] == 1
        assert any(c["decision"] == "skip" for c in payload["confirmations"])

    def test_skip_requires_detected_metric(self, client, seeded_image):
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "reviewer-skip",
                "decisions": [
                    {"decision": "skip"},
                ],
            },
        )
        assert resp.status_code == 400


def _count_chart_facts(db_adapter, filing_id, metric_id, img_id):
    rows = db_adapter.query(
        """
        SELECT 1 FROM v2_metric_facts
         WHERE doc_id = %(doc_id)s
           AND canonical_metric_id = %(metric_id)s
           AND source_type = 'chart'
           AND source_locator ->> 'img_id' = %(img_id)s
        """,
        {"doc_id": filing_id, "metric_id": metric_id, "img_id": img_id},
    )
    return len(rows)


class TestFactPromotion:
    def _post(self, client, body):
        return client.post("/api/v2/image-metric-confirmations", json=body)

    def test_accept_promotes_fact(self, client, db_adapter, seeded_image):
        filing_id = db_adapter.query(
            "SELECT doc_id FROM v2_image_assets WHERE img_id = %(img_id)s",
            {"img_id": seeded_image},
        )[0]["doc_id"]
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "promo-reviewer",
                "decisions": [
                    {"detected_metric_id": "cm_revenue_by_cohort", "decision": "accept"},
                ],
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert _count_chart_facts(db_adapter, filing_id, "cm_revenue_by_cohort", seeded_image) == 1

    def test_reject_does_not_promote_fact(self, client, db_adapter, seeded_image):
        filing_id = db_adapter.query(
            "SELECT doc_id FROM v2_image_assets WHERE img_id = %(img_id)s",
            {"img_id": seeded_image},
        )[0]["doc_id"]
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "reject-reviewer",
                "decisions": [
                    {
                        "detected_metric_id": "cm_revenue_by_cohort",
                        "decision": "reject",
                        "rejection_reason": "not_present",
                    },
                ],
            },
        )
        assert resp.status_code == 200
        assert _count_chart_facts(db_adapter, filing_id, "cm_revenue_by_cohort", seeded_image) == 0

    def test_correct_rolls_back_and_promotes_new(self, client, db_adapter, seeded_image):
        filing_id = db_adapter.query(
            "SELECT doc_id FROM v2_image_assets WHERE img_id = %(img_id)s",
            {"img_id": seeded_image},
        )[0]["doc_id"]
        # First accept the detected metric
        self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "correct-reviewer",
                "decisions": [
                    {"detected_metric_id": "cm_revenue_by_cohort", "decision": "accept"},
                ],
            },
        )
        assert _count_chart_facts(db_adapter, filing_id, "cm_revenue_by_cohort", seeded_image) == 1

        # Correct to a different metric
        resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "correct-reviewer",
                "decisions": [
                    {
                        "detected_metric_id": "cm_revenue_by_cohort",
                        "confirmed_metric_id": "cm_customer_retention_rate",
                        "decision": "correct",
                    },
                ],
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert _count_chart_facts(db_adapter, filing_id, "cm_revenue_by_cohort", seeded_image) == 0
        assert (
            _count_chart_facts(db_adapter, filing_id, "cm_customer_retention_rate", seeded_image)
            == 1
        )

    def test_delete_confirmation_rolls_back_fact(self, client, db_adapter, seeded_image):
        filing_id = db_adapter.query(
            "SELECT doc_id FROM v2_image_assets WHERE img_id = %(img_id)s",
            {"img_id": seeded_image},
        )[0]["doc_id"]
        # Accept
        post_resp = self._post(
            client,
            {
                "img_id": seeded_image,
                "reviewer_id": "undo-reviewer",
                "decisions": [
                    {"detected_metric_id": "cm_revenue_by_cohort", "decision": "accept"},
                ],
            },
        )
        assert post_resp.status_code == 200
        confirmations = post_resp.get_json()["confirmations"]
        confirmation_id = next(
            c["confirmation_id"]
            for c in confirmations
            if c["detected_metric_id"] == "cm_revenue_by_cohort"
        )
        assert _count_chart_facts(db_adapter, filing_id, "cm_revenue_by_cohort", seeded_image) == 1

        # Undo
        del_resp = client.delete(
            f"/api/v2/image-metric-confirmations/{confirmation_id}",
            headers={"X-Reviewer-Id": "undo-reviewer"},
        )
        assert del_resp.status_code == 200, del_resp.get_data(as_text=True)
        assert _count_chart_facts(db_adapter, filing_id, "cm_revenue_by_cohort", seeded_image) == 0
