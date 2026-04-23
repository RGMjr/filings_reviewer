"""
Integration test: round-trip ImageAsset.detected_metrics through Postgres.

Verifies that `V2PersistenceAdapter._persist_images_in_tx` serializes and
persists ``detected_metrics`` to the ``v2_image_assets.detected_metrics``
JSONB column, and that re-extraction via ON CONFLICT (doc_id, filename)
overwrites the column with the latest values.

Requires ``TEST_DATABASE_URL``; skips otherwise.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

from src.extraction_v2.models import (
    DetectedMetric,
    ImageAsset,
    ImageClassification,
)
from src.extraction_v2.persistence import V2PersistenceAdapter
from src.infra.db import DatabaseAdapter

pytestmark = pytest.mark.integration


def _test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def db_adapter() -> DatabaseAdapter:
    url = _test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return DatabaseAdapter(url)


@pytest.fixture(scope="module")
def persistence_adapter(db_adapter: DatabaseAdapter) -> V2PersistenceAdapter:
    return V2PersistenceAdapter(db_adapter)


@pytest.fixture
def test_filing_id(db_adapter: DatabaseAdapter) -> int:
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, ticker)
                VALUES ('9999999998', 'V2 Presence Test Co', 'V2PRES')
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
                """
            )
            company_id = cur.fetchone()["company_id"]
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, cik, accession_number, form_type, filing_date, sec_html_url
                )
                VALUES (
                    %(company_id)s, '9999999998', '9999999998-99-999998',
                    'S-1', '2026-01-01', 'https://www.sec.gov/presence-test/filing.htm'
                )
                ON CONFLICT (company_id, accession_number) DO UPDATE SET
                    form_type = EXCLUDED.form_type
                RETURNING filing_id
                """,
                {"company_id": company_id},
            )
            return cur.fetchone()["filing_id"]


@pytest.fixture(autouse=True)
def cleanup_image_rows(db_adapter: DatabaseAdapter, test_filing_id: int):
    def _cleanup():
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM v2_image_assets WHERE doc_id = %s", (test_filing_id,))

    _cleanup()
    yield
    _cleanup()


def _read_detected_metrics(db: DatabaseAdapter, doc_id: int, filename: str):
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT detected_metrics
                  FROM v2_image_assets
                 WHERE doc_id = %s AND filename = %s
                """,
                (doc_id, filename),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return row["detected_metrics"]


def _new_image(filename: str, metrics: list[DetectedMetric]) -> ImageAsset:
    return ImageAsset(
        img_id=str(uuid.uuid4()),
        filename=filename,
        classification=ImageClassification.CHART,
        detected_metrics=metrics,
    )


class TestDetectedMetricsPersistence:
    def test_persists_detected_metrics_as_jsonb(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        image = _new_image(
            "chart_001.png",
            [
                DetectedMetric(metric_id="cm_revenue_by_cohort", score=0.95),
                DetectedMetric(metric_id="cm_balance_by_cohort", score=0.72),
            ],
        )

        persistence_adapter.persist_images([image], test_filing_id)

        stored = _read_detected_metrics(db_adapter, test_filing_id, "chart_001.png")
        assert stored is not None
        if isinstance(stored, str):
            stored = json.loads(stored)
        assert stored == [
            {"metric_id": "cm_revenue_by_cohort", "score": 0.95},
            {"metric_id": "cm_balance_by_cohort", "score": 0.72},
        ]

    def test_empty_detected_metrics_round_trips_as_empty_list(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        image = _new_image("chart_empty.png", [])

        persistence_adapter.persist_images([image], test_filing_id)

        stored = _read_detected_metrics(db_adapter, test_filing_id, "chart_empty.png")
        assert stored is not None
        if isinstance(stored, str):
            stored = json.loads(stored)
        assert stored == []

    def test_reextraction_overwrites_detected_metrics(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        first = _new_image(
            "chart_002.png",
            [DetectedMetric(metric_id="cm_revenue_by_cohort", score=0.80)],
        )
        persistence_adapter.persist_images([first], test_filing_id)

        second = _new_image(
            "chart_002.png",
            [
                DetectedMetric(metric_id="cm_gross_margin_by_cohort", score=0.91),
                DetectedMetric(metric_id="cm_revenue_by_cohort", score=0.85),
            ],
        )
        persistence_adapter.persist_images([second], test_filing_id)

        stored = _read_detected_metrics(db_adapter, test_filing_id, "chart_002.png")
        assert stored is not None
        if isinstance(stored, str):
            stored = json.loads(stored)
        assert stored == [
            {"metric_id": "cm_gross_margin_by_cohort", "score": 0.91},
            {"metric_id": "cm_revenue_by_cohort", "score": 0.85},
        ]
