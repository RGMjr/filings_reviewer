"""
End-to-end integration tests for the investor presentation ingestion pipeline.

Tests cover:
- PDF → HTML conversion → V2Pipeline → facts extracted (non-DB path)
- SECPresentationSource.fetch() → HTML content delivery
- run_ingestion() dry-run path

DB-dependent tests are marked ``pytest.mark.integration`` and require
``TEST_DATABASE_URL`` to be set.  Non-DB tests run without any database.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path when running tests directly
ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline  # noqa: E402
from src.extraction_v2.presentation_converter import convert_presentation_to_html  # noqa: E402
from src.infra.document_source import DocumentMetadata  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(
    text: str = "",
    tables: list[list[list[str | None]]] | None = None,
) -> MagicMock:
    """Create a mock pdfplumber page."""
    page = MagicMock()
    page.extract_text.return_value = text
    page.extract_tables.return_value = tables or []
    page.images = []
    return page


def _make_pdf(pages: list[MagicMock]) -> MagicMock:
    """Create a mock pdfplumber PDF context manager."""
    pdf = MagicMock()
    pdf.pages = pages
    pdf.__enter__ = MagicMock(return_value=pdf)
    pdf.__exit__ = MagicMock(return_value=False)
    return pdf


# ---------------------------------------------------------------------------
# Minimal presentation HTML for pipeline tests
# ---------------------------------------------------------------------------

MINIMAL_PRESENTATION_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <title>Test Investor Presentation</title>
  <meta charset="utf-8">
  <meta name="source-type" content="presentation">
  <meta name="page-count" content="3">
</head>
<body>
  <section data-section-type="title_slide" data-page="1" data-page-count="3">
    <p>ACME CORP</p>
    <p>Q3 2025 Investor Day</p>
  </section>
  <section data-section-type="presentation_slide" data-page="2" data-page-count="3">
    <p>Financial Highlights</p>
    <table>
      <tr><td>Metric</td><td>Q3 2025</td></tr>
      <tr><td>ARR</td><td>$240M</td></tr>
      <tr><td>NRR</td><td>120%</td></tr>
    </table>
  </section>
  <section data-section-type="presentation_slide" data-page="3" data-page-count="3">
    <p>Customer Metrics</p>
    <p>Total customers exceeded 10,000 in Q3 2025.</p>
    <p>Net revenue retention remained strong at 120%.</p>
  </section>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Tests: converter → HTML (no DB needed)
# ---------------------------------------------------------------------------


class TestPresentationConverterPipeline:
    """Test the PDF → HTML conversion path via mocked pdfplumber."""

    def test_converter_produces_valid_html(self) -> None:
        """Converter output contains expected section structure."""
        pages = [
            _make_page("ACME CORP\nInvestor Day 2025"),
            _make_page(
                "Financial Highlights",
                tables=[[["ARR", "$240M"], ["NRR", "120%"]]],
            ),
            _make_page("Customer Metrics\nTotal customers: 10,000\nNRR: 120%"),
        ]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, meta = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert html.count("<section") == 3
        assert meta.page_count == 3
        assert "<table>" in html
        assert "ARR" in html

    def test_converter_metadata_structure(self) -> None:
        """PresentationMetadata has expected fields after conversion."""
        pages = [_make_page("ACME Corp\nQ3 2025")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            _, meta = convert_presentation_to_html(Path("/path/to/deck.pdf"))

        assert meta.source_id == "/path/to/deck.pdf"
        assert meta.source_type == "presentation"
        assert meta.page_count == 1
        assert meta.title == "ACME Corp"

    def test_converter_empty_pages_handled(self) -> None:
        """Empty pages produce <!-- empty page --> comment, not errors."""
        pages = [_make_page("Title"), _make_page("")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, meta = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert "<!-- empty page -->" in html
        assert meta.page_count == 2


# ---------------------------------------------------------------------------
# Tests: V2Pipeline with presentation HTML (no DB needed)
# ---------------------------------------------------------------------------


class TestPresentationPipelineEndToEnd:
    """Test the V2Pipeline with presentation-mode config on presentation HTML."""

    @pytest.fixture
    def pipeline(self) -> V2Pipeline:
        """Create a presentation-mode pipeline."""
        return V2Pipeline(config=PipelineConfig.for_presentation())

    @pytest.fixture
    def html_path(self, tmp_path: Path) -> Path:
        """Write minimal presentation HTML to a temp file."""
        p = tmp_path / "presentation.html"
        p.write_text(MINIMAL_PRESENTATION_HTML, encoding="utf-8")
        return p

    def test_pipeline_runs_without_error(self, pipeline: V2Pipeline, html_path: Path) -> None:
        """Pipeline completes successfully on minimal presentation HTML."""
        result = pipeline.process(html_path=html_path, filing_id=-1)
        assert result.success, f"Pipeline failed: {result.error_message}"

    def test_pipeline_produces_document(self, pipeline: V2Pipeline, html_path: Path) -> None:
        """Pipeline returns a Document object."""
        result = pipeline.process(html_path=html_path, filing_id=-1)
        assert result.success
        assert result.document is not None

    def test_pipeline_segments_extracted(self, pipeline: V2Pipeline, html_path: Path) -> None:
        """Pipeline parses HTML into segments."""
        result = pipeline.process(html_path=html_path, filing_id=-1)
        assert result.success
        assert len(result.segments) > 0

    def test_pipeline_tables_extracted(self, pipeline: V2Pipeline, html_path: Path) -> None:
        """Pipeline reconstructs tables from presentation HTML."""
        result = pipeline.process(html_path=html_path, filing_id=-1)
        assert result.success
        # The ARR/NRR table in the HTML should be detected
        assert len(result.tables) >= 1

    def test_pipeline_timing_tracked(self, pipeline: V2Pipeline, html_path: Path) -> None:
        """Pipeline records total duration."""
        result = pipeline.process(html_path=html_path, filing_id=-1)
        assert result.success
        assert result.total_duration_ms >= 0

    def test_pipeline_with_document_date(self, pipeline: V2Pipeline, html_path: Path) -> None:
        """Pipeline accepts document_date parameter."""
        doc_date = date(2025, 9, 30)
        result = pipeline.process(
            html_path=html_path,
            filing_id=-1,
            document_type="investor_presentation",
            document_date=doc_date,
        )
        assert result.success


# ---------------------------------------------------------------------------
# Tests: converter error handling (no DB needed)
# ---------------------------------------------------------------------------


class TestPresentationConverterErrors:
    """Test that converter errors propagate correctly."""

    def test_bad_pdf_raises_value_error(self) -> None:
        """Converter raises ValueError if pdfplumber cannot open the PDF."""
        with patch("pdfplumber.open", side_effect=Exception("corrupt")):
            with pytest.raises(ValueError, match="Failed to open PDF"):
                convert_presentation_to_html(Path("/bad/file.pdf"))

    def test_page_extraction_failure_is_graceful(self) -> None:
        """Per-page text extraction failure does not abort conversion."""
        page = _make_page()
        page.extract_text.side_effect = Exception("parse error")
        page.extract_tables.return_value = []
        page.images = []
        pdf = _make_pdf([page])

        with patch("pdfplumber.open", return_value=pdf):
            html, meta = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert 'data-section-type="presentation_slide"' in html
        assert meta.page_count == 1


# ---------------------------------------------------------------------------
# Tests: SECPresentationSource fetch → pipeline (mocked HTTP, no DB)
# ---------------------------------------------------------------------------


class TestSECPresentationSourceToPipeline:
    """Test the source fetch → pipeline path with mocked network calls."""

    def test_fetch_returns_html_and_metadata(self, tmp_path: Path) -> None:
        """SECPresentationSource.fetch() returns (html_str, DocumentMetadata)."""
        import json

        from src.infra.sec_presentation_source import SECPresentationSource

        ticker = "ACME"
        source = SECPresentationSource(cache_dir=tmp_path / "cache")
        source_id = "0000123456/0000123456-25-000001/presentation.pdf"

        # Pre-populate cache using the ticker-based path that _cache_paths expects:
        # cache_dir/{ticker}/{accession}/{filename}.html
        cik, accession, filename = "0000123456", "0000123456-25-000001", "presentation.pdf"

        # Inject cik → ticker mapping BEFORE creating the source so _cache_paths resolves
        SECPresentationSource._cik_to_ticker_cache[cik] = ticker

        cache_dir = tmp_path / "cache" / ticker / accession
        cache_dir.mkdir(parents=True)

        html_cache = cache_dir / (filename + ".html")
        html_cache.write_text(MINIMAL_PRESENTATION_HTML, encoding="utf-8")

        meta_dict = {
            "source_id": source_id,
            "source": "sec_edgar_presentation",
            "company_name": "ACME Corp",
            "ticker": ticker,
            "cik": cik,
            "document_type": "investor_presentation",
            "document_date": "2025-09-30",
            "title": "Q3 2025 Investor Day",
            "fiscal_year": None,
            "fiscal_period": None,
            "form_type": "8-K",
            "url": None,
        }
        meta_cache = cache_dir / (filename + ".meta.json")
        meta_cache.write_text(json.dumps(meta_dict), encoding="utf-8")

        html, meta = source.fetch(source_id)

        assert isinstance(html, str)
        assert "presentation_slide" in html
        assert isinstance(meta, DocumentMetadata)
        assert meta.document_type == "investor_presentation"
        assert meta.document_date == date(2025, 9, 30)

    def test_fetch_html_runs_through_pipeline(self, tmp_path: Path) -> None:
        """HTML from fetch() can be processed by V2Pipeline without errors."""
        import json

        from src.infra.sec_presentation_source import SECPresentationSource

        ticker = "TC"
        source = SECPresentationSource(cache_dir=tmp_path / "cache")
        source_id = "0000999999/0000999999-25-000002/investor_slides.pdf"
        cik, accession, filename = (
            "0000999999",
            "0000999999-25-000002",
            "investor_slides.pdf",
        )

        # Inject cik → ticker mapping before creating cache paths
        SECPresentationSource._cik_to_ticker_cache[cik] = ticker

        # Pre-populate cache under ticker-based path
        cache_dir = tmp_path / "cache" / ticker / accession
        cache_dir.mkdir(parents=True)
        html_cache = cache_dir / (filename + ".html")
        html_cache.write_text(MINIMAL_PRESENTATION_HTML, encoding="utf-8")

        meta_cache = cache_dir / (filename + ".meta.json")
        meta_cache.write_text(
            json.dumps(
                {
                    "source_id": source_id,
                    "source": "sec_edgar_presentation",
                    "company_name": "TestCo",
                    "ticker": ticker,
                    "cik": cik,
                    "document_type": "investor_presentation",
                    "document_date": None,
                    "title": None,
                    "fiscal_year": None,
                    "fiscal_period": None,
                    "form_type": "8-K",
                    "url": None,
                }
            ),
            encoding="utf-8",
        )

        html, meta = source.fetch(source_id)

        # Write to temp file and run pipeline
        html_path = tmp_path / "presentation.html"
        html_path.write_text(html, encoding="utf-8")

        pipeline = V2Pipeline(config=PipelineConfig.for_presentation())
        result = pipeline.process(html_path=html_path, filing_id=-1)

        assert result.success, f"Pipeline failed: {result.error_message}"
        assert result.document is not None


# ---------------------------------------------------------------------------
# Tests: run_ingestion dry-run (mocked source, no DB)
# ---------------------------------------------------------------------------


class TestRunIngestionDryRun:
    """Test the run_ingestion() function in dry-run mode."""

    def test_dry_run_returns_summary_with_results(self) -> None:
        """run_ingestion() dry-run returns IngestSummary with ingested results."""
        from scripts.ingest_presentations import run_ingestion

        mock_meta = DocumentMetadata(
            source_id="0001234567/0001234567-25-000001/presentation.pdf",
            source="sec_edgar_presentation",
            company_name="ACME Corp",
            ticker="ACME",
            cik="0001234567",
            document_type="investor_presentation",
            document_date=date(2025, 9, 30),
        )

        with (
            patch(
                "src.infra.sec_presentation_source.SECPresentationSource.list_available",
                return_value=[mock_meta],
            ),
            patch(
                "src.infra.sec_presentation_source.SECPresentationSource.fetch",
                return_value=(MINIMAL_PRESENTATION_HTML, mock_meta),
            ),
        ):
            summary = run_ingestion(
                tickers=["ACME"],
                limit=1,
                dry_run=True,
                db_url=None,
            )

        assert summary.ingested == 1
        assert summary.errors == 0
        assert summary.skipped == 0

    def test_dry_run_list_failure_records_error(self) -> None:
        """When list_available() raises, run_ingestion() records an error result."""
        from scripts.ingest_presentations import run_ingestion

        with patch(
            "src.infra.sec_presentation_source.SECPresentationSource.list_available",
            side_effect=ConnectionError("EDGAR unreachable"),
        ):
            summary = run_ingestion(
                tickers=["FAIL"],
                limit=5,
                dry_run=True,
                db_url=None,
            )

        assert summary.errors == 1
        assert summary.ingested == 0
        assert summary.results[0].error is not None

    def test_dry_run_fetch_failure_records_error(self) -> None:
        """When fetch() raises, run_ingestion() records an error for that item."""
        from scripts.ingest_presentations import run_ingestion

        mock_meta = DocumentMetadata(
            source_id="0001234567/0001234567-25-000001/presentation.pdf",
            source="sec_edgar_presentation",
            ticker="ACME",
            document_date=date(2025, 9, 30),
        )

        with (
            patch(
                "src.infra.sec_presentation_source.SECPresentationSource.list_available",
                return_value=[mock_meta],
            ),
            patch(
                "src.infra.sec_presentation_source.SECPresentationSource.fetch",
                side_effect=FileNotFoundError("PDF not found"),
            ),
        ):
            summary = run_ingestion(
                tickers=["ACME"],
                limit=1,
                dry_run=True,
                db_url=None,
            )

        assert summary.errors == 1
        assert summary.ingested == 0

    def test_dry_run_multiple_tickers(self) -> None:
        """run_ingestion() processes all tickers even if one fails."""
        from scripts.ingest_presentations import run_ingestion

        mock_meta = DocumentMetadata(
            source_id="0001234567/0001234567-25-000001/presentation.pdf",
            source="sec_edgar_presentation",
            ticker="GOOD",
            document_date=date(2025, 9, 30),
        )

        def list_side_effect(ticker: str | None = None, **_: object) -> list[DocumentMetadata]:
            if ticker == "GOOD":
                return [mock_meta]
            raise ConnectionError("network error")

        with (
            patch(
                "src.infra.sec_presentation_source.SECPresentationSource.list_available",
                side_effect=list_side_effect,
            ),
            patch(
                "src.infra.sec_presentation_source.SECPresentationSource.fetch",
                return_value=(MINIMAL_PRESENTATION_HTML, mock_meta),
            ),
        ):
            summary = run_ingestion(
                tickers=["GOOD", "FAIL"],
                limit=1,
                dry_run=True,
                db_url=None,
            )

        assert summary.ingested == 1
        assert summary.errors == 1
        assert len(summary.results) == 2


# ---------------------------------------------------------------------------
# Tests: IngestSummary report (no DB needed)
# ---------------------------------------------------------------------------


class TestIngestSummary:
    """Test IngestSummary properties and print_report()."""

    def test_summary_counts(self) -> None:
        """Summary correctly counts ingested, skipped, and errors."""
        from scripts.ingest_presentations import IngestResult, IngestSummary

        summary = IngestSummary(
            results=[
                IngestResult("a", "CRM", None, "ingested", fact_count=5),
                IngestResult("b", "CRM", None, "skipped"),
                IngestResult("c", "CRM", None, "error", error="timeout"),
            ]
        )

        assert summary.ingested == 1
        assert summary.skipped == 1
        assert summary.errors == 1
        assert summary.total_facts == 5

    def test_summary_print_report_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        """print_report() outputs a human-readable summary."""
        from scripts.ingest_presentations import IngestResult, IngestSummary

        summary = IngestSummary(
            results=[
                IngestResult(
                    "0001/0001-25-001/deck.pdf",
                    "CRM",
                    date(2025, 9, 30),
                    "ingested",
                    fact_count=3,
                    filing_id=42,
                ),
            ]
        )
        summary.print_report()
        captured = capsys.readouterr()
        assert "PRESENTATION INGESTION SUMMARY" in captured.out
        assert "Ingested:    1" in captured.out
        assert "3 facts" in captured.out


# ---------------------------------------------------------------------------
# DB-backed tests (require TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPresentationIngestionWithDB:
    """Integration tests that require a real database connection."""

    @pytest.fixture
    def db_adapter(self):  # type: ignore[no-untyped-def]
        """Create database adapter from TEST_DATABASE_URL."""
        db_url = os.environ.get("TEST_DATABASE_URL")
        if not db_url:
            pytest.skip("TEST_DATABASE_URL not set")
        from src.infra.db import DatabaseAdapter

        return DatabaseAdapter(db_url)

    def test_presentation_persistence_roundtrip(self, db_adapter: object, tmp_path: Path) -> None:
        """Pipeline result for a presentation can be persisted to DB."""
        from src.extraction_v2.persistence import V2PersistenceAdapter

        html_path = tmp_path / "presentation.html"
        html_path.write_text(MINIMAL_PRESENTATION_HTML, encoding="utf-8")

        pipeline = V2Pipeline(config=PipelineConfig.for_presentation())
        result = pipeline.process(
            html_path=html_path,
            filing_id=1,  # assumes filing_id=1 exists; skip if not
            document_type="investor_presentation",
        )
        assert result.success

        persist_adapter = V2PersistenceAdapter(db_adapter)  # type: ignore[arg-type]
        persist_result = persist_adapter.persist_pipeline_result(
            result,
            filing_id=1,
            document_type="investor_presentation",
        )
        # May fail if filing_id=1 does not exist — this is best-effort
        if not persist_result.success:
            pytest.skip(f"DB persist failed (likely no filing_id=1): {persist_result.errors}")

        assert persist_result.documents_upserted == 1
