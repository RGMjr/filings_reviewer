"""
Integration tests for V2 earnings call transcript pipeline (AC-10).

Covers 8 annotated transcripts end-to-end, validating:
- Pipeline executes successfully on transcript input
- Facts are extracted with valid metric IDs and provenance
- Recall/precision against manual_annotations.csv meet floor thresholds
- TranscriptConverter produces valid semantic HTML
- DB schema (migration 11) handles nullable CIK and new columns

Example:
    # Non-DB tests (no PostgreSQL required):
    pytest tests/integration/extraction_v2/test_transcript_e2e.py -v -k "not DB"

    # Full suite including DB tests:
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \\
        pytest tests/integration/extraction_v2/test_transcript_e2e.py -v

    # Verify 8 transcripts are covered:
    pytest tests/integration/extraction_v2/test_transcript_e2e.py --collect-only \\
        -q -k "test_pipeline_succeeds"
    # Should show 8 parametrized variants
"""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path
from typing import Any

import pytest

from src.extraction_v2.pipeline import (
    DOC_TYPE_TRANSCRIPT,
    PipelineConfig,
    PipelineResult,
    V2Pipeline,
)
from src.extraction_v2.transcript_converter import convert_transcript_to_html
from src.infra.db import DatabaseAdapter

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
TRANSCRIPTS_DIR = _PROJECT_ROOT / "data" / "spike_samples" / "transcripts"
ANNOTATIONS_CSV = _PROJECT_ROOT / "data" / "spike_samples" / "manual_annotations.csv"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The 8 annotated transcripts — (ticker, date_str) matches filename TICKER_DATE.txt
ANNOTATED_TRANSCRIPTS: list[tuple[str, str]] = [
    ("ADBE", "2025-03-12"),
    ("ADSK", "2025-02-27"),
    ("CRM", "2025-02-26"),
    ("GDDY", "2025-05-01"),
    ("META", "2025-04-30"),
    ("MSFT", "2025-04-30"),
    ("PYPL", "2025-04-29"),
    ("TMUS", "2025-04-24"),
]

# Synthetic filing_id used for non-DB pipeline runs
_SYNTHETIC_FILING_ID = 99999

# High-confidence (ticker, date_str, metric_id, expected_value) spot checks.
# These are all v2_likely=yes in manual_annotations.csv with explicit numeric values.
SPOT_CHECK_EXTRACTIONS: list[tuple[str, str, str, float]] = [
    ("CRM", "2025-02-26", "cm_arr", 900_000_000),
    ("META", "2025-04-30", "cm_daily_active_users", 3_400_000_000),
    ("ADBE", "2025-03-12", "cm_arr", 17_630_000_000),
    ("GDDY", "2025-05-01", "cm_customers_period_end", 20_500_000),
    ("PYPL", "2025-04-29", "cm_active_customers_total", 436_000_000),
    ("TMUS", "2025-04-24", "cm_customers_period_end", 25_500_000),
    ("MSFT", "2025-04-30", "cm_customers_period_end", 430_000_000),
    ("MSFT", "2025-04-30", "cm_monthly_active_users", 50_000_000),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_transcript_path(ticker: str, date_str: str) -> Path:
    """Return path to transcript .txt file."""
    return TRANSCRIPTS_DIR / f"{ticker}_{date_str}.txt"


def _convert_and_process(
    ticker: str,
    date_str: str,
    pipeline: V2Pipeline,
    tmp_dir: Path,
    filing_id: int,
) -> PipelineResult | None:
    """
    Convert a transcript .txt to HTML and run the V2 pipeline.

    Returns None if the source .txt file is not present (graceful skip).
    """
    txt_path = _get_transcript_path(ticker, date_str)
    if not txt_path.exists():
        return None

    text = txt_path.read_text(encoding="utf-8")
    html, _ = convert_transcript_to_html(text, title=f"{ticker} Earnings Call {date_str}")

    html_path = tmp_dir / f"{ticker}_{date_str}.html"
    html_path.write_text(html, encoding="utf-8")

    return pipeline.process(html_path=html_path, filing_id=filing_id)


def _load_annotations() -> list[dict[str, Any]]:
    """Load manual_annotations.csv as list of dicts."""
    if not ANNOTATIONS_CSV.exists():
        return []
    with ANNOTATIONS_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _match_facts(
    facts: list[Any],
    metric_id: str,
    expected_value: float,
    tolerance: float = 0.05,
) -> bool:
    """
    Check if any extracted fact matches (metric_id, value) within tolerance.

    Uses relative tolerance: |actual - expected| <= tolerance * |expected|.
    """
    for fact in facts:
        if fact.canonical_metric_id != metric_id:
            continue
        if fact.value is None:
            continue
        try:
            actual = float(fact.value)
        except (TypeError, ValueError):
            continue
        denom = max(abs(expected_value), 1.0)
        if abs(actual - expected_value) <= tolerance * denom:
            return True
    return False


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def transcript_pipeline() -> V2Pipeline:
    """Transcript-tuned V2Pipeline, module-scoped to avoid repeated init overhead."""
    return V2Pipeline(config=PipelineConfig.for_transcript())


@pytest.fixture(scope="module")
def _tmp_html_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Module-scoped temp dir for converted HTML files."""
    return tmp_path_factory.mktemp("transcript_html")


@pytest.fixture(scope="module")
def transcript_results(
    transcript_pipeline: V2Pipeline,
    _tmp_html_dir: Path,
) -> dict[str, PipelineResult]:
    """
    Run the transcript pipeline on all 8 annotated transcripts once per session.

    Returns dict mapping "TICKER_DATE" -> PipelineResult.
    Missing .txt files are silently omitted (caller should pytest.skip).
    """
    results: dict[str, PipelineResult] = {}
    for ticker, date_str in ANNOTATED_TRANSCRIPTS:
        key = f"{ticker}_{date_str}"
        result = _convert_and_process(
            ticker, date_str, transcript_pipeline, _tmp_html_dir, _SYNTHETIC_FILING_ID
        )
        if result is not None:
            results[key] = result
    return results


@pytest.fixture(scope="module")
def annotations() -> list[dict[str, Any]]:
    """Parsed manual_annotations.csv, module-scoped."""
    return _load_annotations()


# ---------------------------------------------------------------------------
# DB fixtures (module-scoped, skipped if TEST_DATABASE_URL not set)
# ---------------------------------------------------------------------------


def _get_test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def db_adapter() -> DatabaseAdapter | None:  # type: ignore[return]
    """Create DatabaseAdapter; skip entire DB test class if URL not configured."""
    url = _get_test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return DatabaseAdapter(url)


@pytest.fixture(scope="module")
def test_transcript_filing_id(db_adapter: DatabaseAdapter) -> int:
    """
    Create a test filing row with document_type='earnings_call' and cik=NULL.

    Uses a dedicated test company (cik='7777777777') to isolate from other tests.
    """
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            # Ensure test company exists
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, ticker)
                VALUES ('7777777777', 'Transcript E2E Test Co', 'TXTE')
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
                """
            )
            company_id = cur.fetchone()["company_id"]

            # Remove any leftover test filings from previous runs
            cur.execute(
                "DELETE FROM filings WHERE company_id = %s AND document_type = 'earnings_call'",
                (company_id,),
            )

            # Insert transcript filing with cik=NULL in filings (key migration 11 feature)
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, form_type, document_type, ticker,
                    document_date, transcript_source
                ) VALUES (
                    %(company_id)s, 'earnings_call', 'earnings_call', 'CRM',
                    '2025-02-26', 'test:transcript_e2e'
                )
                RETURNING filing_id
                """,
                {"company_id": company_id},
            )
            return cur.fetchone()["filing_id"]


# ---------------------------------------------------------------------------
# Class 1: TestTranscriptConfigPropagation — no I/O, lightweight
# ---------------------------------------------------------------------------


class TestTranscriptConfigPropagation:
    """Verify PipelineConfig.for_transcript() sets transcript-appropriate defaults."""

    def test_for_transcript_disables_images(self) -> None:
        config = PipelineConfig.for_transcript()
        assert config.enable_image_extraction is False
        assert config.enable_chart_extraction is False

    def test_for_transcript_widens_proximity(self) -> None:
        """Transcripts need wider proximity window than dense SEC table text."""
        config = PipelineConfig.for_transcript()
        assert config.text_proximity_chars == 400
        assert config.text_proximity_chars > PipelineConfig().text_proximity_chars

    def test_for_transcript_relaxes_fp_filter(self) -> None:
        """Transcript language patterns differ from SEC prose; FP filter must be relaxed."""
        config = PipelineConfig.for_transcript()
        assert config.relaxed_fp_filter is True

    def test_for_transcript_sets_document_type(self) -> None:
        config = PipelineConfig.for_transcript()
        assert config.document_type == DOC_TYPE_TRANSCRIPT

    def test_for_transcript_overrides_respected(self) -> None:
        """Keyword overrides must take priority over factory defaults."""
        config = PipelineConfig.for_transcript(text_proximity_chars=600)
        assert config.text_proximity_chars == 600
        # Other defaults still apply
        assert config.relaxed_fp_filter is True


# ---------------------------------------------------------------------------
# Class 2: TestTranscriptConverterIntegration — file I/O, no pipeline
# ---------------------------------------------------------------------------


class TestTranscriptConverterIntegration:
    """Verify convert_transcript_to_html() output quality across real transcripts."""

    @pytest.fixture(scope="class")
    def sample_transcript(self) -> str:
        """Load one transcript for structural tests."""
        # Use CRM as canonical sample (reliable speaker-turn format)
        path = _get_transcript_path("CRM", "2025-02-26")
        if not path.exists():
            pytest.skip(f"Sample transcript not found: {path}")
        return path.read_text(encoding="utf-8")

    def test_converter_produces_valid_html(self, sample_transcript: str) -> None:
        html, _ = convert_transcript_to_html(sample_transcript)
        assert "<html>" in html
        assert "<body>" in html
        assert "<section" in html, "Expected at least one <section> element"
        assert "<p>" in html, "Expected at least one <p> element"
        assert (
            'class="speaker-turn"' in html or 'class="operator"' in html
        ), "Expected speaker-turn or operator divs"

    def test_converter_extracts_metadata(self, sample_transcript: str) -> None:
        _, metadata = convert_transcript_to_html(sample_transcript)
        has_identifier = metadata.ticker is not None or metadata.company_name is not None
        assert has_identifier, (
            "Expected metadata.ticker or metadata.company_name to be populated; "
            f"got ticker={metadata.ticker!r}, company_name={metadata.company_name!r}"
        )

    def test_sentence_splitting_active(self, sample_transcript: str) -> None:
        """HTML must produce more <p> elements than raw text has newlines."""
        html, _ = convert_transcript_to_html(sample_transcript)
        raw_newlines = sample_transcript.count("\n")
        html_paragraphs = html.count("<p>")
        assert html_paragraphs > raw_newlines, (
            f"Expected sentence splitting to produce more <p> ({html_paragraphs}) "
            f"than raw newlines ({raw_newlines}). Sentence splitting may not be active."
        )

    def test_all_annotated_transcripts_convert(self) -> None:
        """All 8 annotated transcript files must convert without exception."""
        missing = []
        errors = []
        for ticker, date_str in ANNOTATED_TRANSCRIPTS:
            path = _get_transcript_path(ticker, date_str)
            if not path.exists():
                missing.append(f"{ticker}_{date_str}")
                continue
            try:
                text = path.read_text(encoding="utf-8")
                html, meta = convert_transcript_to_html(text)
                assert len(html) > 100, f"{ticker}_{date_str}: HTML suspiciously short"
            except Exception as exc:
                errors.append(f"{ticker}_{date_str}: {exc}")

        if missing:
            pytest.skip(f"Missing transcript files: {missing}")
        assert not errors, "Conversion errors:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# Class 3: TestTranscriptPipelineE2E — core 8-transcript parametrized tests
# ---------------------------------------------------------------------------


class TestTranscriptPipelineE2E:
    """
    End-to-end pipeline tests parametrized over 8 annotated transcripts.

    All tests use the module-scoped `transcript_results` dict to avoid
    re-running the pipeline for each test function.

    Satisfies AC-10: "end-to-end transcript pipeline on 5+ transcripts."
    """

    def _get_result(
        self,
        transcript_results: dict[str, PipelineResult],
        ticker: str,
        date_str: str,
    ) -> PipelineResult:
        """Look up result or skip if transcript was not available."""
        key = f"{ticker}_{date_str}"
        result = transcript_results.get(key)
        if result is None:
            pytest.skip(f"Transcript file not found: {_get_transcript_path(ticker, date_str)}")
        return result  # type: ignore[return-value]  # pytest.skip raises

    @pytest.mark.parametrize("ticker,date_str", ANNOTATED_TRANSCRIPTS)
    def test_pipeline_succeeds(
        self,
        transcript_results: dict[str, PipelineResult],
        ticker: str,
        date_str: str,
    ) -> None:
        """Pipeline must report success=True and a non-None document."""
        result = self._get_result(transcript_results, ticker, date_str)
        assert (
            result.success is True
        ), f"{ticker}_{date_str}: pipeline failed — {result.error_message}"
        assert result.document is not None, f"{ticker}_{date_str}: result.document is None"

    @pytest.mark.parametrize("ticker,date_str", ANNOTATED_TRANSCRIPTS)
    def test_extracts_nonzero_facts(
        self,
        transcript_results: dict[str, PipelineResult],
        ticker: str,
        date_str: str,
    ) -> None:
        """Each transcript must yield at least one extracted metric fact."""
        result = self._get_result(transcript_results, ticker, date_str)
        assert result.fact_count > 0, (
            f"{ticker}_{date_str}: zero facts extracted. "
            f"Segments parsed: {len(result.segments)}"
        )

    @pytest.mark.parametrize("ticker,date_str", ANNOTATED_TRANSCRIPTS)
    def test_facts_have_valid_metric_ids(
        self,
        transcript_results: dict[str, PipelineResult],
        ticker: str,
        date_str: str,
    ) -> None:
        """Every extracted fact must have a canonical_metric_id starting with 'cm_'."""
        result = self._get_result(transcript_results, ticker, date_str)
        bad = [
            f.canonical_metric_id
            for f in result.facts
            if not f.canonical_metric_id.startswith("cm_")
        ]
        assert not bad, f"{ticker}_{date_str}: facts with invalid metric IDs: {bad[:5]}"

    @pytest.mark.parametrize("ticker,date_str", ANNOTATED_TRANSCRIPTS)
    def test_facts_have_provenance(
        self,
        transcript_results: dict[str, PipelineResult],
        ticker: str,
        date_str: str,
    ) -> None:
        """Every fact must have source_locator and non-empty snippet_html."""
        result = self._get_result(transcript_results, ticker, date_str)
        for fact in result.facts:
            assert (
                fact.source_locator is not None
            ), f"{ticker}_{date_str}: fact {fact.fact_id} missing source_locator"
            has_location = (
                fact.source_locator.dom_locator is not None
                or fact.source_locator.segment_id is not None
            )
            assert (
                has_location
            ), f"{ticker}_{date_str}: fact {fact.fact_id} has no dom_locator or segment_id"
            assert (
                fact.evidence_pack is not None
            ), f"{ticker}_{date_str}: fact {fact.fact_id} missing evidence_pack"
            assert (
                fact.evidence_pack.snippet_html
            ), f"{ticker}_{date_str}: fact {fact.fact_id} has empty snippet_html"

    @pytest.mark.parametrize("ticker,date_str", ANNOTATED_TRANSCRIPTS)
    def test_image_stages_skipped(
        self,
        transcript_results: dict[str, PipelineResult],
        ticker: str,
        date_str: str,
    ) -> None:
        """Transcript config disables image extraction; no image assets expected."""
        result = self._get_result(transcript_results, ticker, date_str)
        assert len(result.images) == 0, (
            f"{ticker}_{date_str}: expected 0 image assets for transcript, "
            f"got {len(result.images)}"
        )

    @pytest.mark.parametrize("ticker,date_str", ANNOTATED_TRANSCRIPTS)
    def test_completes_under_10_seconds(
        self,
        transcript_pipeline: V2Pipeline,
        _tmp_html_dir: Path,
        ticker: str,
        date_str: str,
    ) -> None:
        """Each transcript must complete within 10 seconds (performance gate)."""
        txt_path = _get_transcript_path(ticker, date_str)
        if not txt_path.exists():
            pytest.skip(f"Transcript file not found: {txt_path}")

        text = txt_path.read_text(encoding="utf-8")
        html, _ = convert_transcript_to_html(text)
        html_path = _tmp_html_dir / f"perf_{ticker}_{date_str}.html"
        html_path.write_text(html, encoding="utf-8")

        start = time.time()
        result = transcript_pipeline.process(html_path=html_path, filing_id=_SYNTHETIC_FILING_ID)
        elapsed = time.time() - start

        assert result.success, f"{ticker}_{date_str}: pipeline failed"
        assert elapsed < 10.0, (
            f"{ticker}_{date_str}: took {elapsed:.1f}s, exceeds 10s gate. "
            f"Reported duration: {result.total_duration_ms}ms"
        )


# ---------------------------------------------------------------------------
# Class 4: TestTranscriptAnnotationValidation — recall/precision scoring
# ---------------------------------------------------------------------------


class TestTranscriptAnnotationValidation:
    """
    Validate extraction quality against manual_annotations.csv.

    Recall floor: 40% of v2_likely=yes annotations with numeric values are matched.
    Precision floor: 30% of extracted facts match a v2_likely=yes annotation.
    Note: the annotation set is sparse (~77 rows vs. hundreds of extracted facts),
    so precision is underestimated relative to true accuracy. The floor is a
    regression guard, not a full precision target.
    """

    def _yes_numeric_annotations(self, annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter to v2_likely=yes rows with explicit numeric values."""
        result = []
        for row in annotations:
            if row.get("v2_likely") != "yes":
                continue
            val = row.get("value", "").strip()
            if not val:
                continue
            try:
                float(val)
                result.append(row)
            except ValueError:
                continue
        return result

    def test_aggregate_recall_above_floor(
        self,
        transcript_results: dict[str, PipelineResult],
        annotations: list[dict[str, Any]],
    ) -> None:
        """
        Recall >= 40% across all v2_likely=yes annotations with numeric values.

        A "match" is any extracted fact in the same transcript with the same
        canonical_metric_id and a value within 5% of the annotated value.
        """
        if not annotations:
            pytest.skip(f"Annotations CSV not found at {ANNOTATIONS_CSV}")

        yes_numeric = self._yes_numeric_annotations(annotations)
        if not yes_numeric:
            pytest.skip("No v2_likely=yes annotations with numeric values found")

        matched = 0
        skipped = 0
        for row in yes_numeric:
            ticker = row["ticker"]
            date_str = row["date"]
            metric_id = row["metric_id"]
            expected_value = float(row["value"])

            key = f"{ticker}_{date_str}"
            result = transcript_results.get(key)
            if result is None:
                skipped += 1
                continue

            if _match_facts(result.facts, metric_id, expected_value):
                matched += 1

        evaluated = len(yes_numeric) - skipped
        if evaluated == 0:
            pytest.skip("All annotated transcripts were missing — cannot evaluate recall")

        recall = matched / evaluated
        assert recall >= 0.40, (
            f"Aggregate recall {recall:.1%} ({matched}/{evaluated}) is below 40% floor. "
            f"Skipped {skipped} annotations (missing transcripts)."
        )

    def test_aggregate_precision_above_floor(
        self,
        transcript_results: dict[str, PipelineResult],
        annotations: list[dict[str, Any]],
    ) -> None:
        """
        Precision >= 30%: at least 30% of extracted facts match a v2_likely=yes annotation.

        Precision is computed across all 8 transcripts combined. The floor is
        intentionally low because the annotation set is sparse (77 rows total) — many
        correct extractions simply aren't annotated.
        """
        if not annotations:
            pytest.skip(f"Annotations CSV not found at {ANNOTATIONS_CSV}")

        # Build lookup: (ticker, date_str) -> list of (metric_id, value)
        yes_lookup: dict[str, list[tuple[str, float]]] = {}
        for row in self._yes_numeric_annotations(annotations):
            key = f"{row['ticker']}_{row['date']}"
            yes_lookup.setdefault(key, []).append((row["metric_id"], float(row["value"])))

        total_facts = 0
        matched_facts = 0

        for key, result in transcript_results.items():
            ticker, date_str = key.rsplit("_", 1)
            yes_entries = yes_lookup.get(key, [])

            for fact in result.facts:
                if fact.value is None:
                    continue
                total_facts += 1
                for metric_id, expected in yes_entries:
                    if _match_facts([fact], metric_id, expected):
                        matched_facts += 1
                        break

        if total_facts == 0:
            pytest.skip("No facts extracted across any transcript — cannot compute precision")

        precision = matched_facts / total_facts
        assert precision >= 0.30, (
            f"Aggregate precision {precision:.1%} ({matched_facts}/{total_facts}) "
            f"is below 30% floor. The annotation set is sparse; this floor guards "
            f"against regressions in false-positive rate, not absolute precision."
        )

    def test_spot_check_high_confidence_extractions(
        self,
        transcript_results: dict[str, PipelineResult],
    ) -> None:
        """
        At least 5 of the 8 high-confidence spot-check extractions must be present.

        These are v2_likely=yes annotations with clear, unambiguous numeric values
        that the pipeline is expected to reliably capture.
        """
        passed = []
        failed = []

        for ticker, date_str, metric_id, expected_value in SPOT_CHECK_EXTRACTIONS:
            key = f"{ticker}_{date_str}"
            result = transcript_results.get(key)
            label = f"{ticker}/{metric_id}={expected_value:.0f}"
            if result is None:
                failed.append(f"{label} (transcript missing)")
                continue
            if _match_facts(result.facts, metric_id, expected_value):
                passed.append(label)
            else:
                failed.append(f"{label} (not in {result.fact_count} extracted facts)")

        assert len(passed) >= 5, (
            f"Only {len(passed)}/8 spot checks passed (need ≥5).\n"
            f"  Passed: {passed}\n"
            f"  Failed: {failed}"
        )


# ---------------------------------------------------------------------------
# Class 5: TestTranscriptDBSchema — requires TEST_DATABASE_URL, migration 11
# ---------------------------------------------------------------------------


class TestTranscriptDBSchema:
    """
    Verify migration 11 DB schema supports earnings call transcripts.

    Skipped automatically if TEST_DATABASE_URL is not set.
    """

    @pytest.fixture(autouse=True)
    def cleanup_v2_tables(
        self,
        db_adapter: DatabaseAdapter,
        test_transcript_filing_id: int,
    ) -> None:
        """Delete V2 rows for the test transcript filing before and after each test."""

        def _cleanup() -> None:
            with db_adapter.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM v2_metric_facts WHERE doc_id = %s",
                        (test_transcript_filing_id,),
                    )
                    cur.execute(
                        "DELETE FROM v2_segments WHERE doc_id = %s",
                        (test_transcript_filing_id,),
                    )
                    cur.execute(
                        "DELETE FROM v2_documents WHERE filing_id = %s",
                        (test_transcript_filing_id,),
                    )

        _cleanup()
        yield  # type: ignore[misc]
        _cleanup()

    def test_insert_transcript_filing_no_cik(self, db_adapter: DatabaseAdapter) -> None:
        """
        INSERT into filings with cik=NULL must succeed after migration 11.

        Verifies the ALTER COLUMN cik DROP NOT NULL migration applied.
        """
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                # Ensure a company exists
                cur.execute(
                    """
                    SELECT company_id FROM companies WHERE cik = '7777777777' LIMIT 1
                    """
                )
                row = cur.fetchone()
                assert row is not None, "Test company must be created by fixture"
                company_id = row["company_id"]

                # Insert transcript filing without cik/accession_number/sec_html_url
                cur.execute(
                    """
                    INSERT INTO filings (
                        company_id, form_type, document_type, ticker,
                        document_date, transcript_source
                    ) VALUES (
                        %(company_id)s, 'earnings_call', 'earnings_call', 'CRM',
                        '2025-02-26', 'test:no_cik_check'
                    )
                    RETURNING filing_id
                    """,
                    {"company_id": company_id},
                )
                filing_id = cur.fetchone()["filing_id"]
                assert filing_id is not None

                # Cleanup this extra row
                cur.execute("DELETE FROM filings WHERE filing_id = %s", (filing_id,))

    def test_query_by_document_type(
        self,
        db_adapter: DatabaseAdapter,
        test_transcript_filing_id: int,
    ) -> None:
        """WHERE document_type='earnings_call' must return the transcript filing."""
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT filing_id FROM filings
                    WHERE filing_id = %s AND document_type = 'earnings_call'
                    """,
                    (test_transcript_filing_id,),
                )
                row = cur.fetchone()
                assert row is not None, (
                    f"Filing {test_transcript_filing_id} not found with "
                    "document_type='earnings_call'"
                )

    def test_query_by_ticker(
        self,
        db_adapter: DatabaseAdapter,
        test_transcript_filing_id: int,
    ) -> None:
        """WHERE ticker='CRM' must return the transcript filing row."""
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT filing_id FROM filings
                    WHERE filing_id = %s AND ticker = 'CRM'
                    """,
                    (test_transcript_filing_id,),
                )
                row = cur.fetchone()
                assert (
                    row is not None
                ), f"Filing {test_transcript_filing_id} not found with ticker='CRM'"

    def test_document_date_roundtrip(
        self,
        db_adapter: DatabaseAdapter,
        test_transcript_filing_id: int,
    ) -> None:
        """document_date must store and retrieve correctly."""
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT document_date FROM filings WHERE filing_id = %s",
                    (test_transcript_filing_id,),
                )
                row = cur.fetchone()
                assert row is not None
                doc_date = row["document_date"]
                assert doc_date is not None, "document_date should not be NULL"
                # Stored as '2025-02-26'
                assert str(doc_date) == "2025-02-26", f"Expected '2025-02-26', got {doc_date!r}"

    def test_transcript_source_stored(
        self,
        db_adapter: DatabaseAdapter,
        test_transcript_filing_id: int,
    ) -> None:
        """transcript_source column must store a HuggingFace-style identifier."""
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT transcript_source FROM filings WHERE filing_id = %s",
                    (test_transcript_filing_id,),
                )
                row = cur.fetchone()
                assert row is not None
                source = row["transcript_source"]
                assert source is not None, "transcript_source should not be NULL"
                assert ":" in source, f"Expected 'namespace:identifier' format, got {source!r}"
