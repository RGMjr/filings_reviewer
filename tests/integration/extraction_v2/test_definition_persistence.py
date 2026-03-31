"""
Integration tests for V2 metric definition persistence.

These tests require a running PostgreSQL database.
Set TEST_DATABASE_URL environment variable to run.

Example:
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \
        pytest tests/integration/extraction_v2/test_definition_persistence.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

from src.extraction_v2.models import (
    Document,
    MetricDefinition,
)
from src.extraction_v2.persistence import V2PersistenceAdapter
from src.extraction_v2.pipeline import PipelineResult
from src.infra.db import DatabaseAdapter

# Skip all tests if no database connection
pytestmark = pytest.mark.integration


def get_test_db_url() -> str | None:
    """Get test database URL from environment."""
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def db_adapter() -> DatabaseAdapter | None:
    """Create database adapter for tests."""
    url = get_test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
        return None
    return DatabaseAdapter(url)


@pytest.fixture(scope="module")
def persistence_adapter(db_adapter: DatabaseAdapter) -> V2PersistenceAdapter:
    """Create persistence adapter for tests."""
    return V2PersistenceAdapter(db_adapter)


@pytest.fixture
def test_filing_id(db_adapter: DatabaseAdapter) -> int:
    """Create or get a test filing for foreign key references."""
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            # First, ensure we have a test company
            cur.execute("""
                INSERT INTO companies (cik, company_name, ticker)
                VALUES ('8888888881', 'Def Test Company', 'DEFT')
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
            """)
            result = cur.fetchone()
            company_id = result["company_id"]

            # Then create a test filing
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, cik, accession_number, form_type, filing_date, sec_html_url
                )
                VALUES (
                    %(company_id)s, '8888888881', '8888888881-88-888881',
                    'S-1', '2026-01-01', 'https://www.sec.gov/test/def_filing.htm'
                )
                ON CONFLICT (company_id, accession_number) DO UPDATE SET
                    form_type = EXCLUDED.form_type
                RETURNING filing_id
            """,
                {"company_id": company_id},
            )
            result = cur.fetchone()
            return result["filing_id"]


@pytest.fixture(autouse=True)
def cleanup_v2_tables(db_adapter: DatabaseAdapter, test_filing_id: int):
    """Clean up V2 tables before and after each test."""

    def _cleanup():
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                # Delete in order respecting foreign keys
                cur.execute(
                    "DELETE FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                cur.execute("DELETE FROM v2_metric_facts WHERE doc_id = %s", (test_filing_id,))
                cur.execute("DELETE FROM v2_image_assets WHERE doc_id = %s", (test_filing_id,))
                cur.execute(
                    """
                    DELETE FROM v2_table_cells
                    WHERE table_id IN (
                        SELECT table_id FROM v2_tables WHERE doc_id = %s
                    )
                """,
                    (test_filing_id,),
                )
                cur.execute("DELETE FROM v2_tables WHERE doc_id = %s", (test_filing_id,))
                cur.execute("DELETE FROM v2_segments WHERE doc_id = %s", (test_filing_id,))
                cur.execute("DELETE FROM v2_documents WHERE filing_id = %s", (test_filing_id,))

    _cleanup()
    # Create v2_documents row required by FK on v2_metric_definitions.doc_id
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO v2_documents (filing_id, parse_version, status)
                VALUES (%s, '2.0.0', 'complete')
                ON CONFLICT (filing_id) DO NOTHING
                """,
                (test_filing_id,),
            )
    yield
    _cleanup()


def make_definition(
    metric_id: str,
    alignment: str = "unknown",
    **overrides: object,
) -> MetricDefinition:
    """Build a MetricDefinition with sensible defaults."""
    defaults: dict[str, object] = {
        "definition_id": str(uuid.uuid4()),
        "doc_id": str(uuid.uuid4()),
        "canonical_metric_id": metric_id,
        "definition_text": "Customers who placed at least one order in the period.",
        "definition_text_normalized": "Customers who placed at least one order in the period.",
        "alignment_flag": alignment,
    }
    defaults.update(overrides)
    return MetricDefinition(**defaults)  # type: ignore[arg-type]


class TestDefinitionPersistence:
    """Tests for metric definition persistence."""

    def test_persist_single_definition(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ) -> None:
        """Test inserting a single metric definition."""
        defn = make_definition("cm_new_customers_acquired", alignment="aligned")

        count = persistence_adapter.persist_definitions([defn], test_filing_id)

        assert count == 1

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row["canonical_metric_id"] == "cm_new_customers_acquired"
                assert row["alignment_flag"] == "aligned"
                assert (
                    row["definition_text_normalized"]
                    == "Customers who placed at least one order in the period."
                )

    def test_persist_multiple_definitions(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ) -> None:
        """Test inserting multiple metric definitions at once."""
        d1 = make_definition("cm_new_customers_acquired")
        d2 = make_definition("cm_customers_period_end")
        d3 = make_definition("cm_revenue_by_cohort")

        count = persistence_adapter.persist_definitions([d1, d2, d3], test_filing_id)

        assert count == 3

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                result = cur.fetchone()
                assert result["cnt"] == 3

    def test_persist_empty_definitions(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ) -> None:
        """Test persisting empty list returns 0 and stores nothing."""
        count = persistence_adapter.persist_definitions([], test_filing_id)

        assert count == 0

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                result = cur.fetchone()
                assert result["cnt"] == 0

    def test_persist_definition_idempotent(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ) -> None:
        """Test that re-persisting the same metric_id upserts (not duplicates)."""
        defn_original = make_definition(
            "cm_new_customers_acquired",
            definition_text_normalized="Original",
        )
        persistence_adapter.persist_definitions([defn_original], test_filing_id)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                assert cur.fetchone()["cnt"] == 1

        defn_updated = make_definition(
            "cm_new_customers_acquired",
            definition_text_normalized="Updated",
        )
        count = persistence_adapter.persist_definitions([defn_updated], test_filing_id)

        assert count == 1

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt, MAX(definition_text_normalized) AS norm_text "
                    "FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                row = cur.fetchone()
                assert row["cnt"] == 1
                assert row["norm_text"] == "Updated"

    def test_persist_alignment_flags(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ) -> None:
        """Test each alignment flag value round-trips correctly."""
        # Use distinct metric IDs so there is no upsert conflict within the batch
        flag_cases = [
            ("cm_new_customers_acquired", "aligned"),
            ("cm_customers_period_end", "partial"),
            ("cm_revenue_by_cohort", "not_aligned"),
            ("cm_transactions_by_cohort", "unknown"),
        ]

        definitions = [make_definition(metric_id, alignment=flag) for metric_id, flag in flag_cases]

        count = persistence_adapter.persist_definitions(definitions, test_filing_id)
        assert count == 4

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT canonical_metric_id, alignment_flag "
                    "FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                rows = {r["canonical_metric_id"]: r["alignment_flag"] for r in cur.fetchall()}

        for metric_id, expected_flag in flag_cases:
            assert rows[metric_id] == expected_flag, (
                f"Expected alignment_flag={expected_flag!r} for {metric_id}, "
                f"got {rows.get(metric_id)!r}"
            )


class TestDefinitionPipelineResultIntegration:
    """Tests for definition persistence via PipelineResult."""

    def test_pipeline_result_includes_definitions_count(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_filing_id: int,
    ) -> None:
        """Test that persist_pipeline_result records definitions_upserted."""
        doc = Document(
            doc_id=str(uuid.uuid4()),
            accession="8888888881-88-888881",
            cik="8888888881",
            company="Def Test Company",
            parse_version="2.0.0",
        )

        result = PipelineResult(
            document=doc,
            facts=[],
            tables=[],
            images=[],
            segments=[],
            stage_results=[],
            total_duration_ms=0,
            success=True,
            definitions=[make_definition("cm_new_customers_acquired")],
        )

        persist_result = persistence_adapter.persist_pipeline_result(result, test_filing_id)

        assert persist_result.success
        assert persist_result.definitions_upserted >= 1

    def test_pipeline_result_definitions_idempotent(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ) -> None:
        """Test that persisting the same pipeline result twice does not duplicate definitions."""
        doc = Document(
            doc_id=str(uuid.uuid4()),
            accession="8888888881-88-888881",
            cik="8888888881",
            company="Def Test Company",
            parse_version="2.0.0",
        )

        result = PipelineResult(
            document=doc,
            facts=[],
            tables=[],
            images=[],
            segments=[],
            stage_results=[],
            total_duration_ms=0,
            success=True,
            definitions=[make_definition("cm_new_customers_acquired")],
        )

        persistence_adapter.persist_pipeline_result(result, test_filing_id)
        persistence_adapter.persist_pipeline_result(result, test_filing_id)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM v2_metric_definitions WHERE doc_id = %s",
                    (test_filing_id,),
                )
                row = cur.fetchone()
                assert row["cnt"] == 1
