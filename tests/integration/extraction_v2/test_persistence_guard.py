"""Integration tests for the reviewed-filing persistence guard.

Validates that `V2PersistenceAdapter.persist_facts` and
`persist_pipeline_result` refuse to wipe human review decisions unless the
caller passes ``force=True``.

Requires TEST_DATABASE_URL.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import date

import pytest

from src.extraction_v2.exceptions import ReviewedFilingError
from src.extraction_v2.models import (
    Document,
    EvidencePack,
    ExtractionMethod,
    MetricFact,
    PeriodType,
    ReviewStatus,
    SourceLocator,
    SourceType,
    Unit,
)
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
    """Create a dedicated filing for guard tests (separate CIK from other suites)."""
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, ticker)
                VALUES ('9999999998', 'Guard Test Company', 'GUARD')
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
                    'S-1', '2026-01-01', 'https://www.sec.gov/test/guard.htm'
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
                # v2_review_decisions CASCADEs off facts, but also drop any strays.
                cur.execute(
                    """
                    DELETE FROM v2_review_decisions
                     WHERE fact_id IN (
                        SELECT fact_id FROM v2_metric_facts WHERE doc_id = %s
                     )
                    """,
                    (test_filing_id,),
                )
                cur.execute("DELETE FROM v2_metric_facts WHERE doc_id = %s", (test_filing_id,))
                cur.execute("DELETE FROM v2_documents WHERE filing_id = %s", (test_filing_id,))

    _purge()
    yield
    _purge()


def _make_fact(
    filing_id: int,
    value: float = 100.0,
    period_year: int = 2025,
) -> MetricFact:
    """Build a MetricFact with a unique identity tuple per ``period_year``.

    ``_persist_facts_in_tx`` dedupes by
    (metric, period, unit, scope, cohort), so tests that need multiple
    coexisting facts for the same filing must vary one of those fields.
    """
    return MetricFact(
        fact_id=str(uuid.uuid4()),
        doc_id=str(filing_id),
        canonical_metric_id="cm_new_customers_acquired",
        value=value,
        value_raw=str(value),
        unit=Unit.COUNT,
        period_type=PeriodType.ANNUAL,
        period_start=date(period_year, 1, 1),
        period_end=date(period_year, 12, 31),
        source_type=SourceType.TEXT,
        source_locator=SourceLocator(dom_locator=f"/p[{period_year}]"),
        evidence_pack=EvidencePack(snippet_html=f"<p>{value}</p>"),
        confidence=0.85,
        extraction_method=ExtractionMethod.EXACT_MATCH,
        review_status=ReviewStatus.PENDING_REVIEW,
    )


def _insert_decision(
    db_adapter: DatabaseAdapter,
    fact_id: str,
    reviewer_id: str = "tester@example.com",
    decision: str = "accept",
) -> None:
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO v2_review_decisions (fact_id, decision, reviewer_id)
                VALUES (%s, %s, %s)
                """,
                (fact_id, decision, reviewer_id),
            )


def _decision_count(db_adapter: DatabaseAdapter, filing_id: int) -> int:
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                  FROM v2_review_decisions rd
                  JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
                 WHERE mf.doc_id = %s
                """,
                (filing_id,),
            )
            return int(cur.fetchone()["n"])


class TestGuardOnPersistFacts:
    def test_raises_when_decisions_exist_without_force(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        fact = _make_fact(test_filing_id)
        persistence_adapter.persist_facts([fact], test_filing_id)
        _insert_decision(db_adapter, fact.fact_id, reviewer_id="alice@example.com")

        new_fact = _make_fact(test_filing_id, value=200.0)
        with pytest.raises(ReviewedFilingError) as excinfo:
            persistence_adapter.persist_facts([new_fact], test_filing_id)

        assert excinfo.value.filing_id == test_filing_id
        assert excinfo.value.decision_count == 1
        assert excinfo.value.reviewer_count == 1
        # Original fact + decision untouched
        assert _decision_count(db_adapter, test_filing_id) == 1

    def test_force_purges_and_warns(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
        caplog: pytest.LogCaptureFixture,
    ):
        # Seed two facts in a single persist call so the subsequent decisions
        # both survive. Distinct period_year ensures the identity-tuple dedupe
        # in _persist_facts_in_tx does not collapse them into one row.
        fact_a = _make_fact(test_filing_id, value=100.0, period_year=2024)
        fact_b = _make_fact(test_filing_id, value=150.0, period_year=2025)
        persistence_adapter.persist_facts([fact_a, fact_b], test_filing_id)
        _insert_decision(db_adapter, fact_a.fact_id, reviewer_id="alice@example.com")
        _insert_decision(db_adapter, fact_b.fact_id, reviewer_id="bob@example.com")
        assert _decision_count(db_adapter, test_filing_id) == 2

        new_fact = _make_fact(test_filing_id, value=300.0)
        with caplog.at_level(logging.WARNING, logger="src.extraction_v2.persistence"):
            count = persistence_adapter.persist_facts(
                [new_fact], test_filing_id, force=True
            )
        assert count == 1
        # CASCADE wiped both decisions and the old facts
        assert _decision_count(db_adapter, test_filing_id) == 0
        assert any(
            "force-reextract purging reviewed filing" in rec.message
            and "purged_decision_count=2" in rec.message
            and "distinct_reviewer_count=2" in rec.message
            for rec in caplog.records
        )

    def test_unreviewed_filing_passes_without_force(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        fact = _make_fact(test_filing_id)
        persistence_adapter.persist_facts([fact], test_filing_id)
        # No decision inserted — re-running should succeed.
        new_fact = _make_fact(test_filing_id, value=400.0)
        count = persistence_adapter.persist_facts([new_fact], test_filing_id)
        assert count == 1

    def test_empty_facts_list_returns_zero(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_filing_id: int,
    ):
        # Guard must not error on empty-fact call (early return path).
        count = persistence_adapter.persist_facts([], test_filing_id)
        assert count == 0


class TestGuardOnPipelineResult:
    def test_pipeline_result_respects_guard(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        fact = _make_fact(test_filing_id)
        persistence_adapter.persist_facts([fact], test_filing_id)
        _insert_decision(db_adapter, fact.fact_id)

        result = _make_pipeline_result([_make_fact(test_filing_id, value=999.0)])
        with pytest.raises(ReviewedFilingError):
            persistence_adapter.persist_pipeline_result(result, test_filing_id)
        assert _decision_count(db_adapter, test_filing_id) == 1

    def test_pipeline_result_force_purges(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        fact = _make_fact(test_filing_id)
        persistence_adapter.persist_facts([fact], test_filing_id)
        _insert_decision(db_adapter, fact.fact_id)

        result = _make_pipeline_result([_make_fact(test_filing_id, value=999.0)])
        persist_result = persistence_adapter.persist_pipeline_result(
            result, test_filing_id, force=True
        )
        assert persist_result.success
        assert _decision_count(db_adapter, test_filing_id) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline_result(facts: list[MetricFact]) -> PipelineResult:
    """Minimal PipelineResult suitable for persist_pipeline_result."""
    doc_id = str(uuid.uuid4())
    doc = Document(
        doc_id=doc_id,
        accession="9999999998-99-999998",
        cik="9999999998",
        company="Guard Test Company",
        parse_version="2.0.0",
    )
    return PipelineResult(
        document=doc,
        segments=[],
        tables=[],
        images=[],
        facts=facts,
        definitions=[],
        stage_results=[
            StageResult(
                stage=PipelineStage.FACT_CONSTRUCTION,
                success=True,
                duration_ms=1,
                items_processed=len(facts),
                items_output=len(facts),
            )
        ],
        total_duration_ms=1,
        success=True,
    )
