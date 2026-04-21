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
    ImageAsset,
    ImageClassification,
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
                # v2_image_review_decisions CASCADEs off v2_image_assets.img_id,
                # but purge explicitly in case DELETEs run out of order.
                cur.execute(
                    """
                    DELETE FROM v2_image_review_decisions
                     WHERE img_id IN (
                        SELECT img_id FROM v2_image_assets WHERE doc_id = %s
                     )
                    """,
                    (test_filing_id,),
                )
                cur.execute("DELETE FROM v2_image_assets WHERE doc_id = %s", (test_filing_id,))
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
            count = persistence_adapter.persist_facts([new_fact], test_filing_id, force=True)
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
# Image guard helpers and tests
# ---------------------------------------------------------------------------


def _make_image(
    filename: str = "chart_1.png",
    classification: ImageClassification = ImageClassification.CHART,
) -> ImageAsset:
    """Build an ImageAsset suitable for _persist_images_in_tx."""
    return ImageAsset(
        filename=filename,
        file_path=f"/tmp/{filename}",
        width=800,
        height=600,
        dom_locator=f"/img[{filename}]",
        nearby_text="test caption",
        classification=classification,
        relevance_score=0.8,
        processed=True,
        confidence=0.9,
    )


def _insert_image_decision(
    db_adapter: DatabaseAdapter,
    img_id: str,
    decision: str = "relevant",
) -> None:
    # CHECK constraints in sql/29: relevant => chart_type NOT NULL;
    # not_relevant => rejection_reason NOT NULL.
    chart_type = "other_chart" if decision == "relevant" else None
    rejection_reason = "other" if decision == "not_relevant" else None
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO v2_image_review_decisions
                    (img_id, decision, chart_type, rejection_reason)
                VALUES (%s, %s, %s, %s)
                """,
                (img_id, decision, chart_type, rejection_reason),
            )


def _img_id_for(db_adapter: DatabaseAdapter, filing_id: int, filename: str) -> str:
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT img_id FROM v2_image_assets WHERE doc_id = %s AND filename = %s",
                (filing_id, filename),
            )
            row = cur.fetchone()
            assert row is not None, f"no v2_image_assets row for filename={filename}"
            return str(row["img_id"] if isinstance(row, dict) else row[0])


def _classification_for(db_adapter: DatabaseAdapter, filing_id: int, filename: str) -> str:
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT classification FROM v2_image_assets WHERE doc_id = %s AND filename = %s",
                (filing_id, filename),
            )
            row = cur.fetchone()
            assert row is not None
            return str(row["classification"] if isinstance(row, dict) else row[0])


class TestGuardOnPersistImages:
    def test_reclassification_to_hidden_raises_without_force(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        persistence_adapter.persist_images(
            [_make_image("chart_1.png", ImageClassification.CHART)], test_filing_id
        )
        img_id = _img_id_for(db_adapter, test_filing_id, "chart_1.png")
        _insert_image_decision(db_adapter, img_id)

        with pytest.raises(ReviewedFilingError) as excinfo:
            persistence_adapter.persist_images(
                [_make_image("chart_1.png", ImageClassification.DECORATIVE)],
                test_filing_id,
            )
        assert excinfo.value.filing_id == test_filing_id
        assert excinfo.value.decision_count == 1
        assert excinfo.value.context == "image classifications"
        # Classification preserved on DB; decision still bound
        assert _classification_for(db_adapter, test_filing_id, "chart_1.png") == "chart"

    def test_reclassification_to_hidden_force_warns_and_proceeds(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
        caplog: pytest.LogCaptureFixture,
    ):
        persistence_adapter.persist_images(
            [_make_image("chart_2.png", ImageClassification.CHART)], test_filing_id
        )
        img_id = _img_id_for(db_adapter, test_filing_id, "chart_2.png")
        _insert_image_decision(db_adapter, img_id)

        # persist_images does not expose force; exercise the pipeline path which does.
        result = _make_pipeline_result_with_images(
            images=[_make_image("chart_2.png", ImageClassification.DECORATIVE)]
        )
        with caplog.at_level(logging.WARNING, logger="src.extraction_v2.persistence"):
            persist_result = persistence_adapter.persist_pipeline_result(
                result, test_filing_id, force=True
            )
        assert persist_result.success
        assert _classification_for(db_adapter, test_filing_id, "chart_2.png") == "decorative"
        assert any(
            "force-reextract hiding reviewed images" in rec.message
            and "chart_2.png" in rec.message
            and "hidden_image_count=1" in rec.message
            for rec in caplog.records
        )

    def test_same_classification_passes(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        persistence_adapter.persist_images(
            [_make_image("chart_3.png", ImageClassification.CHART)], test_filing_id
        )
        img_id = _img_id_for(db_adapter, test_filing_id, "chart_3.png")
        _insert_image_decision(db_adapter, img_id)
        # Re-persist with same classification — must not raise.
        persistence_adapter.persist_images(
            [_make_image("chart_3.png", ImageClassification.CHART)], test_filing_id
        )
        assert _classification_for(db_adapter, test_filing_id, "chart_3.png") == "chart"

    def test_unreviewed_image_passes(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # Seed visible image but no decision — re-classify to hidden is allowed.
        persistence_adapter.persist_images(
            [_make_image("chart_4.png", ImageClassification.CHART)], test_filing_id
        )
        persistence_adapter.persist_images(
            [_make_image("chart_4.png", ImageClassification.DECORATIVE)], test_filing_id
        )
        assert _classification_for(db_adapter, test_filing_id, "chart_4.png") == "decorative"

    def test_already_hidden_reclassification_passes(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # A decided image that is already in the hidden set stays hidden — the
        # guard's job is to prevent NEW hiding, not rewrite history.
        persistence_adapter.persist_images(
            [_make_image("logo_1.png", ImageClassification.LOGO)], test_filing_id
        )
        img_id = _img_id_for(db_adapter, test_filing_id, "logo_1.png")
        _insert_image_decision(db_adapter, img_id, decision="not_relevant")
        # Re-classify logo -> decorative (still hidden) — must not raise.
        persistence_adapter.persist_images(
            [_make_image("logo_1.png", ImageClassification.DECORATIVE)], test_filing_id
        )
        assert _classification_for(db_adapter, test_filing_id, "logo_1.png") == "decorative"


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


def _make_pipeline_result_with_images(images: list[ImageAsset]) -> PipelineResult:
    """Minimal PipelineResult carrying images (no facts)."""
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
        images=images,
        facts=[],
        definitions=[],
        stage_results=[
            StageResult(
                stage=PipelineStage.IMAGE_TRIAGE,
                success=True,
                duration_ms=1,
                items_processed=len(images),
                items_output=len(images),
            )
        ],
        total_duration_ms=1,
        success=True,
    )


def _make_chart_fact(
    filing_id: int,
    value: float = 500.0,
    period_year: int = 2025,
) -> MetricFact:
    return MetricFact(
        fact_id=str(uuid.uuid4()),
        doc_id=str(filing_id),
        canonical_metric_id="cm_revenue_by_cohort",
        value=value,
        value_raw=str(value),
        unit=Unit.COUNT,
        period_type=PeriodType.ANNUAL,
        period_start=date(period_year, 1, 1),
        period_end=date(period_year, 12, 31),
        source_type=SourceType.CHART,
        source_locator=SourceLocator(
            dom_locator=f"chart[{period_year}]",
            img_id=str(uuid.uuid4()),
        ),
        evidence_pack=EvidencePack(snippet_html=f"<p>chart {value}</p>"),
        confidence=0.85,
        extraction_method=ExtractionMethod.EXACT_MATCH,
        review_status=ReviewStatus.PENDING_REVIEW,
    )


class TestChartOnlyMode:
    """Verify the `chart_only` persistence path preserves text facts + decisions."""

    def test_chart_only_filters_inbound_to_chart_facts(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        text_fact = _make_fact(test_filing_id, value=100.0, period_year=2024)
        chart_fact = _make_chart_fact(test_filing_id, value=500.0, period_year=2025)

        count = persistence_adapter.persist_facts(
            [text_fact, chart_fact], test_filing_id, chart_only=True
        )
        assert count == 1

        with db_adapter.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT source_type FROM v2_metric_facts WHERE doc_id = %s",
                (test_filing_id,),
            )
            rows = cur.fetchall()
        assert [r["source_type"] for r in rows] == ["chart"]

    def test_chart_only_preserves_existing_text_facts_and_decisions(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # Seed a text fact with a reviewer decision (the thing we must preserve).
        text_fact = _make_fact(test_filing_id, value=100.0, period_year=2024)
        persistence_adapter.persist_facts([text_fact], test_filing_id)
        _insert_decision(db_adapter, text_fact.fact_id, reviewer_id="alice@example.com")
        assert _decision_count(db_adapter, test_filing_id) == 1

        # Chart-only backfill: no force needed; text fact + decision must survive.
        chart_fact = _make_chart_fact(test_filing_id, value=500.0)
        count = persistence_adapter.persist_facts([chart_fact], test_filing_id, chart_only=True)
        assert count == 1

        with db_adapter.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT fact_id, source_type FROM v2_metric_facts WHERE doc_id = %s ORDER BY source_type",
                (test_filing_id,),
            )
            rows = cur.fetchall()
        assert {r["source_type"] for r in rows} == {"chart", "text"}
        assert _decision_count(db_adapter, test_filing_id) == 1
        # Specifically: the text fact's fact_id is unchanged (decision FK intact).
        text_fact_ids = [r["fact_id"] for r in rows if r["source_type"] == "text"]
        assert str(text_fact_ids[0]) == text_fact.fact_id

    def test_chart_only_guard_counts_chart_decisions_only(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # Text-fact decision exists; chart-only mode must NOT treat this as a
        # reason to raise, because we're not touching text facts.
        text_fact = _make_fact(test_filing_id, value=100.0, period_year=2024)
        persistence_adapter.persist_facts([text_fact], test_filing_id)
        _insert_decision(db_adapter, text_fact.fact_id, reviewer_id="alice@example.com")

        chart_fact = _make_chart_fact(test_filing_id, value=500.0)
        # No force=True, no ReviewedFilingError expected.
        count = persistence_adapter.persist_facts([chart_fact], test_filing_id, chart_only=True)
        assert count == 1
        assert _decision_count(db_adapter, test_filing_id) == 1

    def test_chart_only_guard_raises_when_chart_decision_exists(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # Seed a reviewed chart fact — chart_only must raise without force.
        chart_fact = _make_chart_fact(test_filing_id, value=500.0, period_year=2024)
        persistence_adapter.persist_facts([chart_fact], test_filing_id)
        _insert_decision(db_adapter, chart_fact.fact_id, reviewer_id="alice@example.com")

        new_chart = _make_chart_fact(test_filing_id, value=600.0, period_year=2025)
        with pytest.raises(ReviewedFilingError):
            persistence_adapter.persist_facts([new_chart], test_filing_id, chart_only=True)
        assert _decision_count(db_adapter, test_filing_id) == 1

    def test_chart_only_empty_inbound_is_noop(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # Text fact exists; inbound list has no chart facts → nothing happens,
        # including no DELETE that would spuriously wipe chart state.
        text_fact = _make_fact(test_filing_id)
        persistence_adapter.persist_facts([text_fact], test_filing_id)

        count = persistence_adapter.persist_facts([text_fact], test_filing_id, chart_only=True)
        assert count == 0  # filtered-out list is empty

        with db_adapter.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM v2_metric_facts WHERE doc_id = %s",
                (test_filing_id,),
            )
            assert int(cur.fetchone()["n"]) == 1
