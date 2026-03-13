"""
Integration tests for V2 persistence layer.

These tests require a running PostgreSQL database.
Set TEST_DATABASE_URL environment variable to run.

Example:
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \
        pytest tests/integration/extraction_v2/test_persistence.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest

from src.extraction_v2.models import (
    Cell,
    Document,
    EvidencePack,
    ExtractionMethod,
    ImageAsset,
    ImageClassification,
    MetricFact,
    PeriodType,
    ReviewStatus,
    SectionType,
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
    Table,
    Unit,
)
from src.extraction_v2.persistence import PersistenceResult, V2PersistenceAdapter
from src.extraction_v2.pipeline import PipelineResult, PipelineStage, StageResult
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


@pytest.fixture(scope="module")
def test_filing_id(db_adapter: DatabaseAdapter) -> int:
    """Create or get a test filing for foreign key references."""
    # Check if test company/filing exists
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            # First, ensure we have a test company
            cur.execute("""
                INSERT INTO companies (cik, company_name, ticker)
                VALUES ('9999999999', 'V2 Test Company', 'V2TC')
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
                    %(company_id)s, '9999999999', '9999999999-99-999999',
                    'S-1', '2026-01-01', 'https://www.sec.gov/test/filing.htm'
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
    yield
    _cleanup()


class TestDocumentPersistence:
    """Tests for document persistence."""

    def test_persist_new_document(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_filing_id: int,
    ):
        """Test inserting a new document."""
        doc = Document(
            doc_id=str(uuid.uuid4()),
            accession="9999999999-99-999999",
            cik="9999999999",
            company="V2 Test Company",
            parse_version="2.0.0",
        )

        doc_id = persistence_adapter.persist_document(
            document=doc,
            filing_id=test_filing_id,
            segment_count=10,
            table_count=5,
            image_count=3,
            fact_count=15,
            status="complete",
        )

        assert doc_id == doc.doc_id

    def test_update_existing_document(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test upserting an existing document updates counts."""
        doc = Document(
            doc_id=str(uuid.uuid4()),
            accession="9999999999-99-999999",
            parse_version="2.0.0",
        )

        # First insert
        persistence_adapter.persist_document(
            document=doc,
            filing_id=test_filing_id,
            segment_count=10,
            fact_count=5,
        )

        # Update with new counts
        persistence_adapter.persist_document(
            document=doc,
            filing_id=test_filing_id,
            segment_count=20,
            fact_count=10,
        )

        # Verify update
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT segment_count, fact_count FROM v2_documents WHERE filing_id = %s",
                    (test_filing_id,),
                )
                result = cur.fetchone()
                assert result["segment_count"] == 20
                assert result["fact_count"] == 10

    def test_document_computed_stats(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test computed statistics are stored correctly."""
        doc = Document(doc_id=str(uuid.uuid4()))

        persistence_adapter.persist_document(
            document=doc,
            filing_id=test_filing_id,
            segment_count=100,
            table_count=25,
            image_count=10,
            fact_count=50,
            status="complete",
        )

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT segment_count, table_count, image_count, fact_count, status
                       FROM v2_documents WHERE filing_id = %s""",
                    (test_filing_id,),
                )
                result = cur.fetchone()
                assert result["segment_count"] == 100
                assert result["table_count"] == 25
                assert result["image_count"] == 10
                assert result["fact_count"] == 50
                assert result["status"] == "complete"


class TestSegmentPersistence:
    """Tests for segment persistence."""

    def test_persist_segments_batch(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test batch inserting segments."""
        segments = [
            Segment(
                segment_id=str(uuid.uuid4()),
                doc_id=str(test_filing_id),
                segment_type=SegmentType.PARAGRAPH,
                text=f"Segment {i} text content",
                dom_locator=f"/html/body/p[{i}]",
                section_type=SectionType.MDA,
                sequence=i,
            )
            for i in range(5)
        ]

        count = persistence_adapter.persist_segments(segments, test_filing_id)
        assert count == 5

        # Verify in database
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM v2_segments WHERE doc_id = %s", (test_filing_id,)
                )
                result = cur.fetchone()
                assert result["cnt"] == 5

    def test_persist_segments_empty_list(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_filing_id: int,
    ):
        """Test persisting empty segment list returns 0."""
        count = persistence_adapter.persist_segments([], test_filing_id)
        assert count == 0

    def test_segment_ordering_preserved(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test segment sequence ordering is preserved."""
        segments = [
            Segment(
                segment_id=str(uuid.uuid4()),
                segment_type=SegmentType.HEADING,
                text=f"Heading {i}",
                sequence=i * 10,  # Non-sequential to test ordering
            )
            for i in range(3)
        ]

        persistence_adapter.persist_segments(segments, test_filing_id)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT segment_text, sequence_idx
                       FROM v2_segments WHERE doc_id = %s
                       ORDER BY sequence_idx""",
                    (test_filing_id,),
                )
                results = cur.fetchall()
                assert results[0]["sequence_idx"] == 0
                assert results[1]["sequence_idx"] == 10
                assert results[2]["sequence_idx"] == 20


class TestTablePersistence:
    """Tests for table and cell persistence."""

    def test_persist_table_with_cells(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test inserting table with cells."""
        table = Table(
            table_id=str(uuid.uuid4()),
            doc_id=str(test_filing_id),
            dom_locator="/html/body/table[1]",
            row_count=3,
            col_count=2,
            header_rows=1,
            stub_cols=1,
            cells=[
                Cell(row=0, col=0, text="Header 1", is_header=True),
                Cell(row=0, col=1, text="Header 2", is_header=True),
                Cell(row=1, col=0, text="Row 1", is_stub=True),
                Cell(row=1, col=1, text="Value 1"),
                Cell(row=2, col=0, text="Row 2", is_stub=True),
                Cell(row=2, col=1, text="Value 2"),
            ],
        )

        table_count, cell_count = persistence_adapter.persist_tables([table], test_filing_id)
        assert table_count == 1
        assert cell_count == 6

        # Verify cells
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM v2_table_cells WHERE table_id = %s",
                    (table.table_id,),
                )
                result = cur.fetchone()
                assert result["cnt"] == 6

    def test_persist_table_header_stub_paths(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test header_path and stub_path arrays are stored correctly."""
        table = Table(
            table_id=str(uuid.uuid4()),
            row_count=2,
            col_count=2,
            cells=[
                Cell(
                    row=1,
                    col=1,
                    text="100",
                    header_path=["Revenue", "2024"],
                    stub_path=["Q1"],
                ),
            ],
        )

        persistence_adapter.persist_tables([table], test_filing_id)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT header_path, stub_path
                       FROM v2_table_cells
                       WHERE table_id = %s AND row_idx = 1 AND col_idx = 1""",
                    (table.table_id,),
                )
                result = cur.fetchone()
                assert result["header_path"] == ["Revenue", "2024"]
                assert result["stub_path"] == ["Q1"]

    def test_persist_empty_tables(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_filing_id: int,
    ):
        """Test persisting empty table list."""
        table_count, cell_count = persistence_adapter.persist_tables([], test_filing_id)
        assert table_count == 0
        assert cell_count == 0

    def test_persist_table_no_cells(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test persisting table without cells."""
        table = Table(
            table_id=str(uuid.uuid4()),
            row_count=0,
            col_count=0,
            cells=[],
        )

        table_count, cell_count = persistence_adapter.persist_tables([table], test_filing_id)
        assert table_count == 1
        assert cell_count == 0


class TestFactPersistence:
    """Tests for metric fact persistence."""

    def test_persist_fact_with_provenance(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test inserting fact with full provenance."""
        fact = MetricFact(
            fact_id=str(uuid.uuid4()),
            doc_id=str(test_filing_id),
            canonical_metric_id="cm_new_customers_acquired",  # Use valid metric ID
            value=1000000.0,
            value_raw="$1.0M",
            unit=Unit.CURRENCY,
            currency="USD",
            period_type=PeriodType.ANNUAL,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                segment_id="seg-123",
                table_id="table-456",
                cell_row=5,
                cell_col=3,
                dom_locator="/html/body/table[1]/tr[5]/td[3]",
            ),
            evidence_pack=EvidencePack(
                snippet_html="<td>$1.0M</td>",
                header_path=["ARR", "2025"],
                stub_path=["Total"],
                raw_value_text="$1.0M",
            ),
            confidence=0.95,
            extraction_method=ExtractionMethod.EXACT_MATCH,
            requires_review=False,
            review_status=ReviewStatus.AUTO_ACCEPTED,
        )

        count = persistence_adapter.persist_facts([fact], test_filing_id)
        assert count == 1

        # Verify JSONB fields
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT source_locator, evidence_pack, confidence, review_status
                       FROM v2_metric_facts WHERE fact_id = %s""",
                    (fact.fact_id,),
                )
                result = cur.fetchone()
                assert result["source_locator"]["cell_row"] == 5
                assert result["evidence_pack"]["header_path"] == ["ARR", "2025"]
                assert float(result["confidence"]) == 0.95
                assert result["review_status"] == "auto_accepted"

    def test_persist_fact_idempotent(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test updating existing fact (idempotency)."""
        fact_id = str(uuid.uuid4())
        fact = MetricFact(
            fact_id=fact_id,
            canonical_metric_id="cm_new_customers_acquired",  # Use valid metric ID
            value=115.0,
            value_raw="115%",
            unit=Unit.PERCENT,
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(dom_locator="/p[1]"),
            evidence_pack=EvidencePack(snippet_html="<p>115%</p>"),
            confidence=0.80,
        )

        # First insert
        persistence_adapter.persist_facts([fact], test_filing_id)

        # Update with new confidence
        fact.confidence = 0.90
        fact.value = 120.0
        fact.value_raw = "120%"
        persistence_adapter.persist_facts([fact], test_filing_id)

        # Verify update (not duplicate)
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM v2_metric_facts WHERE fact_id = %s", (fact_id,)
                )
                assert cur.fetchone()["cnt"] == 1

                cur.execute(
                    "SELECT confidence, value FROM v2_metric_facts WHERE fact_id = %s", (fact_id,)
                )
                result = cur.fetchone()
                assert float(result["confidence"]) == 0.90
                assert float(result["value"]) == 120.0

    def test_persist_fact_jsonb_round_trip(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test JSONB fields serialize and deserialize correctly."""
        locator = SourceLocator(
            segment_id="seg-abc",
            table_id="table-xyz",
            cell_row=10,
            cell_col=5,
            text_span=(100, 200),
            dom_locator="/html/body/div[2]/table[1]",
        )
        evidence = EvidencePack(
            snippet_html="<td><b>$5M</b></td>",
            header_path=["Revenue", "FY2025", "Actual"],
            stub_path=["Product A", "Enterprise"],
            context_before="Previous quarter showed...",
            context_after="...growing by 20%.",
            raw_value_text="$5M",
        )

        fact = MetricFact(
            fact_id=str(uuid.uuid4()),
            canonical_metric_id="cm_new_customers_acquired",  # Use valid metric ID
            value=5000000.0,
            value_raw="$5M",
            unit=Unit.CURRENCY,
            currency="USD",  # Required when unit is CURRENCY
            source_type=SourceType.HTML_TABLE,
            source_locator=locator,
            evidence_pack=evidence,
        )

        persistence_adapter.persist_facts([fact], test_filing_id)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT source_locator, evidence_pack FROM v2_metric_facts WHERE fact_id = %s",
                    (fact.fact_id,),
                )
                result = cur.fetchone()

                # Verify source_locator
                sl = result["source_locator"]
                assert sl["segment_id"] == "seg-abc"
                assert sl["table_id"] == "table-xyz"
                assert sl["cell_row"] == 10
                assert sl["text_span"] == [100, 200]

                # Verify evidence_pack
                ep = result["evidence_pack"]
                assert ep["header_path"] == ["Revenue", "FY2025", "Actual"]
                assert ep["stub_path"] == ["Product A", "Enterprise"]
                assert "growing by 20%" in ep["context_after"]

    def test_review_status_preserved_on_re_extraction(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        # Re-extraction intentionally resets reviewer decisions — delete-then-insert pattern
        fact = MetricFact(
            fact_id=str(uuid.uuid4()),
            canonical_metric_id="cm_new_customers_acquired",
            value=500.0,
            value_raw="500",
            unit=Unit.COUNT,
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(dom_locator="/p[2]"),
            evidence_pack=EvidencePack(snippet_html="<p>500</p>"),
            confidence=0.85,
            review_status=ReviewStatus.PENDING_REVIEW,
        )

        # Initial insert with PENDING_REVIEW
        persistence_adapter.persist_facts([fact], test_filing_id)

        # Simulate a reviewer accepting the fact directly in DB
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE v2_metric_facts SET review_status = 'accepted' WHERE fact_id = %s",
                    (fact.fact_id,),
                )

        # Re-extraction: delete-then-insert means reviewer status is wiped
        original_fact_id = fact.fact_id
        fact.confidence = 0.92
        fact.review_status = ReviewStatus.PENDING_REVIEW  # extraction always sets pending
        persistence_adapter.persist_facts([fact], test_filing_id)

        # After re-extraction the old row is gone (DELETE) and a fresh row exists with PENDING
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT review_status, confidence FROM v2_metric_facts WHERE fact_id = %s",
                    (original_fact_id,),
                )
                result = cur.fetchone()
                # Delete-then-insert resets reviewer decisions; status is back to PENDING_REVIEW
                assert result["review_status"] == "pending_review", (
                    "Re-extraction should reset review_status to pending (delete-then-insert)"
                )
                assert float(result["confidence"]) == 0.92


class TestImagePersistence:
    """Tests for image asset persistence."""

    def test_persist_image_basic(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test inserting basic image asset."""
        image = ImageAsset(
            img_id=str(uuid.uuid4()),
            doc_id=str(test_filing_id),
            filename="chart1.png",
            file_path="/data/images/chart1.png",
            width=800,
            height=600,
            dom_locator="/html/body/img[1]",
            classification=ImageClassification.CHART,
            relevance_score=0.85,
        )

        count = persistence_adapter.persist_images([image], test_filing_id)
        assert count == 1

    def test_persist_image_with_chart_data(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test image with chart_data JSONB field."""
        from src.extraction_v2.models import ChartData, ChartSeries, ChartType, DataPoint

        chart_data = ChartData(
            chart_type=ChartType.BAR,
            title="Revenue by Quarter",
            x_axis_label="Quarter",
            y_axis_label="Revenue ($M)",
            series=[
                ChartSeries(
                    name="2025",
                    points=[
                        DataPoint(x="Q1", y=10.0, label="$10M"),
                        DataPoint(x="Q2", y=12.0, label="$12M"),
                    ],
                ),
            ],
        )

        image = ImageAsset(
            img_id=str(uuid.uuid4()),
            filename="revenue_chart.png",
            dom_locator="/html/body/img[2]",
            classification=ImageClassification.CHART,
            chart_data=chart_data,
            processed=True,
            confidence=0.90,
        )

        persistence_adapter.persist_images([image], test_filing_id)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT chart_data, chart_type FROM v2_image_assets WHERE img_id = %s",
                    (image.img_id,),
                )
                result = cur.fetchone()
                assert result["chart_type"] == "bar"
                cd = result["chart_data"]
                assert cd["title"] == "Revenue by Quarter"
                assert len(cd["series"]) == 1
                assert cd["series"][0]["points"][0]["y"] == 10.0


class TestPipelineResultPersistence:
    """Tests for full pipeline result persistence."""

    def test_persist_complete_pipeline_result(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test persisting complete PipelineResult in single transaction."""
        doc = Document(doc_id=str(uuid.uuid4()), parse_version="2.0.0")

        segments = [
            Segment(
                segment_id=str(uuid.uuid4()),
                segment_type=SegmentType.PARAGRAPH,
                text="Sample text",
                sequence=0,
            ),
        ]

        table = Table(
            table_id=str(uuid.uuid4()),
            row_count=1,
            col_count=1,
            cells=[Cell(row=0, col=0, text="Value")],
        )

        fact = MetricFact(
            fact_id=str(uuid.uuid4()),
            canonical_metric_id="cm_new_customers_acquired",  # Use valid metric ID
            value=100.0,
            value_raw="100",
            unit=Unit.COUNT,
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(dom_locator="/p[1]"),
            evidence_pack=EvidencePack(snippet_html="<p>100</p>"),
        )

        result = PipelineResult(
            document=doc,
            facts=[fact],
            tables=[table],
            images=[],
            segments=segments,
            stage_results=[
                StageResult(
                    stage=PipelineStage.INGESTION,
                    success=True,
                    duration_ms=100,
                    items_processed=1,
                    items_output=1,
                ),
            ],
            total_duration_ms=1000,
            success=True,
        )

        persist_result = persistence_adapter.persist_pipeline_result(result, test_filing_id)

        assert persist_result.success
        assert persist_result.documents_upserted == 1
        assert persist_result.segments_upserted == 1
        assert persist_result.tables_upserted == 1
        assert persist_result.cells_upserted == 1
        assert persist_result.facts_upserted == 1

    def test_persist_empty_pipeline_result(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_filing_id: int,
    ):
        """Test persisting pipeline result with no extracted data."""
        doc = Document(doc_id=str(uuid.uuid4()))

        result = PipelineResult(
            document=doc,
            facts=[],
            tables=[],
            images=[],
            segments=[],
            stage_results=[],
            total_duration_ms=50,
            success=True,
        )

        persist_result = persistence_adapter.persist_pipeline_result(result, test_filing_id)

        assert persist_result.success
        assert persist_result.documents_upserted == 1
        assert persist_result.total_upserted == 1  # Just the document

    def test_transaction_atomicity(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test that failed persistence rolls back all changes."""
        doc = Document(doc_id=str(uuid.uuid4()))

        # Create a valid segment
        segment = Segment(
            segment_id=str(uuid.uuid4()),
            segment_type=SegmentType.PARAGRAPH,
            text="Valid segment",
            sequence=0,
        )

        # Create a fact with invalid metric_id (should fail constraint)
        # Note: This test assumes the database has a FK constraint to metrics table
        fact = MetricFact(
            fact_id=str(uuid.uuid4()),
            canonical_metric_id="invalid_metric_that_does_not_exist",
            value=100.0,
            value_raw="100",
            unit=Unit.COUNT,
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(),
            evidence_pack=EvidencePack(snippet_html="<p>100</p>"),
        )

        result = PipelineResult(
            document=doc,
            facts=[fact],
            tables=[],
            images=[],
            segments=[segment],
            stage_results=[],
            total_duration_ms=100,
            success=True,
        )

        persist_result = persistence_adapter.persist_pipeline_result(result, test_filing_id)

        # Should fail due to invalid metric_id FK
        assert not persist_result.success
        assert persist_result.errors is not None
        assert len(persist_result.errors) > 0

        # Verify rollback - no document or segment should exist
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM v2_documents WHERE doc_id = %s", (doc.doc_id,)
                )
                assert cur.fetchone()["cnt"] == 0

                cur.execute(
                    "SELECT COUNT(*) as cnt FROM v2_segments WHERE segment_id = %s",
                    (segment.segment_id,),
                )
                assert cur.fetchone()["cnt"] == 0


class TestConcurrentExtraction:
    """Tests for concurrent extraction safety."""

    def test_concurrent_pipeline_persist(
        self,
        persistence_adapter: V2PersistenceAdapter,
        db_adapter: DatabaseAdapter,
        test_filing_id: int,
    ):
        """Test that two concurrent persist operations on different filings don't conflict."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Create two separate test filings
        filing_ids = []
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                for i in range(2):
                    cur.execute(
                        """
                        INSERT INTO companies (cik, company_name, ticker)
                        VALUES (%(cik)s, %(name)s, %(ticker)s)
                        ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                        RETURNING company_id
                    """,
                        {
                            "cik": f"777777777{i}",
                            "name": f"Concurrent Test Co {i}",
                            "ticker": f"CT{i}",
                        },
                    )
                    company_id = cur.fetchone()["company_id"]

                    cur.execute(
                        """
                        INSERT INTO filings (
                            company_id, cik, accession_number, form_type,
                            filing_date, sec_html_url
                        ) VALUES (
                            %(company_id)s, %(cik)s, %(accession)s, 'S-1',
                            '2026-01-01', %(url)s
                        )
                        ON CONFLICT (company_id, accession_number) DO UPDATE SET
                            form_type = EXCLUDED.form_type
                        RETURNING filing_id
                    """,
                        {
                            "company_id": company_id,
                            "cik": f"777777777{i}",
                            "accession": f"777777777{i}-99-99999{i}",
                            "url": f"https://www.sec.gov/test/concurrent_{i}.htm",
                        },
                    )
                    filing_ids.append(cur.fetchone()["filing_id"])

        def persist_for_filing(fid: int, idx: int) -> PersistenceResult:
            """Build and persist a pipeline result for a filing."""
            doc = Document(doc_id=str(uuid.uuid4()), parse_version="2.0.0")
            segments = [
                Segment(
                    segment_id=str(uuid.uuid4()),
                    segment_type=SegmentType.PARAGRAPH,
                    text=f"Concurrent test segment {idx}-{j}",
                    sequence=j,
                )
                for j in range(3)
            ]
            fact = MetricFact(
                fact_id=str(uuid.uuid4()),
                canonical_metric_id="cm_new_customers_acquired",
                value=float(100 + idx),
                value_raw=f"{100 + idx}",
                unit=Unit.COUNT,
                source_type=SourceType.TEXT,
                source_locator=SourceLocator(dom_locator=f"/p[{idx}]"),
                evidence_pack=EvidencePack(snippet_html=f"<p>{100 + idx}</p>"),
            )
            result = PipelineResult(
                document=doc,
                facts=[fact],
                tables=[],
                images=[],
                segments=segments,
                stage_results=[
                    StageResult(
                        stage=PipelineStage.INGESTION,
                        success=True,
                        duration_ms=50,
                        items_processed=1,
                        items_output=1,
                    ),
                ],
                total_duration_ms=100,
                success=True,
            )
            return persistence_adapter.persist_pipeline_result(result, fid)

        # Run two concurrent persists
        results = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(persist_for_filing, fid, idx): fid
                for idx, fid in enumerate(filing_ids)
            }
            for future in as_completed(futures):
                results.append(future.result())

        # Both should succeed
        for i, pr in enumerate(results):
            assert pr.success, f"Concurrent persist {i} failed: {pr.errors}"

        # Verify correct counts in database
        for fid in filing_ids:
            with db_adapter.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM v2_metric_facts WHERE doc_id = %s",
                        (fid,),
                    )
                    assert cur.fetchone()["cnt"] == 1

                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM v2_segments WHERE doc_id = %s",
                        (fid,),
                    )
                    assert cur.fetchone()["cnt"] == 3

        # Cleanup
        for fid in filing_ids:
            with db_adapter.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM v2_metric_facts WHERE doc_id = %s", (fid,))
                    cur.execute("DELETE FROM v2_segments WHERE doc_id = %s", (fid,))
                    cur.execute("DELETE FROM v2_documents WHERE filing_id = %s", (fid,))
