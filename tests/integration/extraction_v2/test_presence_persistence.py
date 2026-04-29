"""
Integration test: round-trip MetricPresence through v2_text_metric_presence.

Verifies _persist_presence_in_tx writes rows via the pipeline-result path,
re-runs are idempotent (UPSERT on (filing_id, canonical_metric_id)), and the
upsert never touches v2_metric_facts or v2_review_decisions. The
presence_only=True mode is exercised in test_persistence_guard.py alongside
the existing fact/image guard suite.

Requires TEST_DATABASE_URL; skips otherwise.
"""

from __future__ import annotations

import os
import uuid

import pytest

from src.extraction_v2.models import Document, MetricPresence
from src.extraction_v2.persistence import V2PersistenceAdapter
from src.extraction_v2.pipeline import PipelineResult, PipelineStage, StageResult
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
                VALUES ('9999999997', 'Presence Round-Trip Co', 'PRESRT')
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
                    %(company_id)s, '9999999997', '9999999997-99-999997',
                    'S-1', '2026-01-01', 'https://www.sec.gov/presence-rt/filing.htm'
                )
                ON CONFLICT (company_id, accession_number) DO UPDATE SET
                    form_type = EXCLUDED.form_type
                RETURNING filing_id
                """,
                {"company_id": company_id},
            )
            return cur.fetchone()["filing_id"]


@pytest.fixture(autouse=True)
def _cleanup(db_adapter: DatabaseAdapter, test_filing_id: int):
    def _purge() -> None:
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM v2_text_metric_presence WHERE filing_id = %s",
                    (test_filing_id,),
                )

    _purge()
    yield
    _purge()


def _make_pipeline_result(presences: list[MetricPresence]) -> PipelineResult:
    doc = Document(
        doc_id=str(uuid.uuid4()),
        accession="9999999997-99-999997",
        cik="9999999997",
        company="Presence Round-Trip Co",
        parse_version="2.0.0",
    )
    return PipelineResult(
        document=doc,
        segments=[],
        tables=[],
        images=[],
        facts=[],
        definitions=[],
        presences=presences,
        stage_results=[
            StageResult(
                stage=PipelineStage.METRIC_PRESENCE,
                success=True,
                duration_ms=1,
                items_processed=len(presences),
                items_output=len(presences),
            )
        ],
        total_duration_ms=1,
        success=True,
    )


def _read_presences(db: DatabaseAdapter, filing_id: int) -> list[dict]:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT canonical_metric_id, score, detected_at_stage,
                       evidence_segment_ids, advisory_value_count, advisory_fact_ids,
                       pipeline_version
                  FROM v2_text_metric_presence
                 WHERE filing_id = %s
                 ORDER BY canonical_metric_id
                """,
                (filing_id,),
            )
            return [dict(row) for row in cur.fetchall()]


class TestPresenceRoundTrip:
    def test_persist_writes_rows(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        result = _make_pipeline_result(
            [
                MetricPresence(
                    canonical_metric_id="cm_net_revenue_retention",
                    score=0.85,
                    detected_at_stage="fact_construction",
                    evidence_segment_ids=["seg-1", "seg-2"],
                    advisory_value_count=2,
                    advisory_fact_ids=[str(uuid.uuid4())],
                ),
                MetricPresence(
                    canonical_metric_id="cm_revenue_by_cohort",
                    score=0.7,
                    detected_at_stage="chart_fact_bridge",
                    evidence_segment_ids=[],
                    advisory_value_count=0,
                    advisory_fact_ids=[],
                ),
            ]
        )

        persist_result = persistence_adapter.persist_pipeline_result(result, test_filing_id)

        assert persist_result.success
        assert persist_result.presences_upserted == 2

        rows = _read_presences(db_adapter, test_filing_id)
        assert [r["canonical_metric_id"] for r in rows] == [
            "cm_net_revenue_retention",
            "cm_revenue_by_cohort",
        ]
        nrr = rows[0]
        assert nrr["score"] == 0.85
        assert nrr["detected_at_stage"] == "fact_construction"
        # JSONB deserializes to list for evidence_segment_ids / advisory_fact_ids
        assert nrr["evidence_segment_ids"] == ["seg-1", "seg-2"]
        assert nrr["advisory_value_count"] == 2
        assert len(nrr["advisory_fact_ids"]) == 1
        assert nrr["pipeline_version"] == "2.0.0"

    def test_re_run_is_idempotent_and_updates(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # First run
        r1 = _make_pipeline_result(
            [
                MetricPresence(
                    canonical_metric_id="cm_a",
                    score=0.6,
                    detected_at_stage="fact_construction",
                )
            ]
        )
        persistence_adapter.persist_pipeline_result(r1, test_filing_id)

        # Second run with higher score — should UPDATE, not INSERT a second row
        r2 = _make_pipeline_result(
            [
                MetricPresence(
                    canonical_metric_id="cm_a",
                    score=0.9,
                    detected_at_stage="fact_construction",
                    evidence_segment_ids=["seg-new"],
                )
            ]
        )
        persistence_adapter.persist_pipeline_result(r2, test_filing_id)

        rows = _read_presences(db_adapter, test_filing_id)
        assert len(rows) == 1
        assert rows[0]["score"] == 0.9
        assert rows[0]["evidence_segment_ids"] == ["seg-new"]

    def test_empty_presences_is_noop(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        result = _make_pipeline_result([])
        persist_result = persistence_adapter.persist_pipeline_result(result, test_filing_id)
        assert persist_result.success
        assert persist_result.presences_upserted == 0
        assert _read_presences(db_adapter, test_filing_id) == []
