"""Integration test for the full-page-OCR pipeline (Issue #82).

Drives `V2Pipeline.process` end-to-end on a synthetic page-scan HTML fixture
with a mocked `VisionClient` and asserts the Path A flow:

- `ImageTriageStage._detect_full_page_scan_filing` fires on a 6-image
  page-shaped fixture with low text density (promotes the filing to
  ``full_page_scan_mode``).
- `OCRExtractionStage.process_full_page_scan` runs on each promoted
  ``FULL_PAGE_SCAN`` asset, writes ``ImageAsset.ocr_text``, and
  synthesizes ``Segment`` rows with ``source_type=IMAGE_OCR``.
- The pipeline's vision-API gate
  (``V2Pipeline._check_vision_api_availability``) doesn't auto-disable
  image extraction when ``OPENAI_API_KEY`` is set in env.

Run:
  TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \\
      pytest tests/integration/extraction_v2/test_full_page_ocr_pipeline.py -v
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.extraction_v2.models import SegmentSourceType
from src.extraction_v2.pipeline import (
    PipelineConfig,
    PipelineResult,
    V2Pipeline,
)
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.infra.db import DatabaseAdapter
from src.llm.vision_client import PageTextExtraction

pytestmark = pytest.mark.integration


# Test CIK chosen to not collide with other integration tests
# (test_e2e_pipeline.py uses "8888888888").
_TEST_CIK = "0009999998"
_TEST_ACCESSION = "0009999998-26-000001"


def _make_page_jpeg(width: int = 1000, height: int = 1300) -> bytes:
    """Generate a portrait-page-shaped JPEG (~6KB).

    Defaults are inside the page-shaped band that
    ``ImageTriageStage._detect_full_page_scan_filing`` accepts:
    aspect ~0.77 (within 0.7–0.85), width within 900–1300.
    """
    img = Image.new("RGB", (width, height), color=(245, 245, 245))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


@pytest.fixture
def full_page_scan_html(tmp_path: Path) -> Path:
    """Build a tempdir with 6 page-shaped JPGs + a stub HTML referencing them.

    Designed to satisfy ``_detect_full_page_scan_filing``:
      - ``image_count == 6`` (>= 5)
      - text density low enough that ``image_count / max(1, text_chars/2000) >= 1.5``
      - all 6 images carry width=1000 height=1300 (page-shaped band)
    """
    img_bytes = _make_page_jpeg()
    image_filenames = [f"page_{i:03d}.jpg" for i in range(6)]
    for name in image_filenames:
        (tmp_path / name).write_bytes(img_bytes)

    html_body = (
        "<html><body>"
        "<p>Investor presentation excerpt; minimal narrative text.</p>"
        + "".join(f'<img src="{name}" width="1000" height="1300" />' for name in image_filenames)
        + "</body></html>"
    )
    html_path = tmp_path / "filing.html"
    html_path.write_text(html_body, encoding="utf-8")
    return html_path


@pytest.fixture(scope="module")
def db_adapter() -> DatabaseAdapter:
    """Database adapter for FK references during pipeline.process().

    Note: `V2Pipeline.process` itself doesn't write to the DB, but stages
    that resolve doc_id/filing_id rely on the row existing.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return DatabaseAdapter(url)


@pytest.fixture
def test_filing_id(db_adapter: DatabaseAdapter) -> int:
    """Idempotently create a unique test company + filing for this test."""
    with db_adapter.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (cik, company_name, ticker)
            VALUES (%s, 'Full Page OCR Test Co', 'FPOCR')
            ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
            RETURNING company_id
            """,
            (_TEST_CIK,),
        )
        company_id = cur.fetchone()["company_id"]
        cur.execute(
            """
            INSERT INTO filings (
                company_id, cik, accession_number, form_type, filing_date, sec_html_url
            )
            VALUES (
                %s, %s, %s, 'S-1', '2026-01-01',
                'https://www.sec.gov/test/full_page_ocr_filing.htm'
            )
            ON CONFLICT (company_id, accession_number) DO UPDATE SET
                form_type = EXCLUDED.form_type
            RETURNING filing_id
            """,
            (company_id, _TEST_CIK, _TEST_ACCESSION),
        )
        return cur.fetchone()["filing_id"]


@pytest.fixture(autouse=True)
def cleanup_v2_tables(db_adapter: DatabaseAdapter, test_filing_id: int):
    """Best-effort cleanup before and after each test."""

    def _cleanup() -> None:
        with db_adapter.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM v2_metric_facts WHERE filing_id = %s", (test_filing_id,))
            cur.execute("DELETE FROM v2_image_assets WHERE filing_id = %s", (test_filing_id,))
            cur.execute("DELETE FROM v2_segments WHERE filing_id = %s", (test_filing_id,))
            cur.execute("DELETE FROM v2_documents WHERE filing_id = %s", (test_filing_id,))

    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def mock_vision_client() -> MagicMock:
    """`VisionClient` mock that returns canned page-OCR text."""
    mock = MagicMock()
    mock.analyze_image_for_text.return_value = PageTextExtraction(
        text=(
            "Customer count: 12,345 enterprise customers as of Q4 2025. "
            "Net revenue retention: 105%. Gross margin: 72%."
        ),
        contains_chart=False,
        contains_table=False,
        chart_hint=None,
        cost_usd=0.0,
        raw_response={"choices": [{"message": {"content": "stub"}}]},
    )
    return mock


def test_full_page_ocr_path_a_synthesizes_image_ocr_segments(
    full_page_scan_html: Path,
    test_filing_id: int,
    mock_vision_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: 6 page-shaped images → triage promotes to FULL_PAGE_SCAN
    → OCR synthesizes ``image_ocr`` segments and populates ``ocr_text``."""
    # gh-619 vision-API gate is provider-aware: full-page-OCR provider (gemini),
    # prescan provider (gemini), and chart-fallback provider (anthropic) each
    # need their respective keys for Stage 5 to enable. Mock all three — the
    # vision_client is monkey-patched below so no real API calls happen.
    monkeypatch.setenv("OPENAI_API_KEY", "test-fake-key-mock-handles-calls")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-fake-key-mock-handles-calls")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-fake-key-mock-handles-calls")

    config = PipelineConfig(
        enable_full_page_ocr=True,
        enable_image_extraction=True,
        enable_chart_extraction=True,
        enable_metric_classify=False,
        enable_image_keyword_prescan=False,
    )
    pipeline = V2Pipeline(config=config)

    # `V2Pipeline.__init__` doesn't take a vision_client; the OCR stage
    # lazy-loads `VisionClient` on first use unless `_vision_client` is
    # already set. Inject the mock directly so no real API calls happen.
    ocr_stage = next(
        (proc for _stage, proc in pipeline._stages if isinstance(proc, OCRExtractionStage)),
        None,
    )
    assert ocr_stage is not None, "OCRExtractionStage missing from pipeline"
    ocr_stage._vision_client = mock_vision_client
    # PR 2: full_page_ocr now routes through _build_cheap_ocr_client; patch it
    # so the mock is used instead of building a real Gemini VisionClient.
    monkeypatch.setattr(
        "src.extraction_v2.stages.ocr_extraction._build_cheap_ocr_client",
        lambda provider, model: mock_vision_client,
    )

    result: PipelineResult = pipeline.process(
        html_path=full_page_scan_html,
        filing_id=test_filing_id,
    )

    assert result.success, f"pipeline failed: error={getattr(result, 'error_message', None)}"

    # All 6 image assets discovered
    assert len(result.images) == 6, f"expected 6 image assets, got {len(result.images)}"

    # Path A processed every page-shaped image
    processed = [img for img in result.images if img.processed]
    assert len(processed) == 6, f"expected all 6 images processed, got {len(processed)}"
    assert all(img.ocr_text for img in processed), (
        "expected ocr_text populated on every processed image"
    )
    assert all("Customer count" in img.ocr_text for img in processed), (
        "expected canned OCR text on processed images"
    )

    # Synthesized segments carry IMAGE_OCR provenance
    image_ocr_segments = [
        s for s in result.segments if s.source_type == SegmentSourceType.IMAGE_OCR
    ]
    assert len(image_ocr_segments) == 6, (
        f"expected 6 image_ocr segments, got {len(image_ocr_segments)}"
    )
    assert all(s.source_img_id for s in image_ocr_segments), (
        "expected every image_ocr segment to carry source_img_id"
    )
    assert all("Customer count" in s.text for s in image_ocr_segments), (
        "expected canned OCR text in segment.text"
    )

    # Vision client was called exactly once per image (no double-billing
    # of Path A + Path B; pre-scan should be skipped because
    # full_page_scan_mode is True).
    assert mock_vision_client.analyze_image_for_text.call_count == 6, (
        f"expected 6 vision calls, got {mock_vision_client.analyze_image_for_text.call_count}"
    )
