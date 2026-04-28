"""
E2E pipeline test for 8-K exhibit 99.1 content extraction (legacy-116).

Verifies that the V2 pipeline correctly processes a combined 8-K HTML file
(primary cover page + exhibit 99.1 concatenated via the exhibit separator)
and extracts segments and metric facts from the exhibit content.

This test is distinct from tests/integration/filing_fetcher/test_8k_exhibit_fetch.py
(legacy-058), which validates only that the fetcher writes the combined HTML
correctly. This test validates the full pipeline processes the combined HTML
and produces meaningful extraction output from the exhibit content.

Fixture:
    data/gold_standard/Samsara_Inc_8K_2025-08-21/filing.html
    — a sanitized 8-K for Samsara Inc. (CIK 1642545, 2025-08-21) combining
      a primary cover page with a synthetic exhibit 99.1 earnings press release.
    — The fixture is test-only; it is not referenced in any gold-standard CSV
      and is excluded from baseline computation (no extracted_values.csv / metadata.json).
    — Fixture size is > 15 KB to clear the pipeline's minimum-size threshold.

Per feedback_zero_facts_can_be_pre_pipeline_failure: the test explicitly
confirms fixture content before asserting pipeline output, so a missing or
malformed fixture produces a clear skip rather than a silent pass on an
empty pipeline result.

Example:
    pytest tests/integration/extraction_v2/test_8k_exhibit_e2e_pipeline.py -x -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.extraction_v2.pipeline import (
    PipelineConfig,
    PipelineResult,
    process_filing,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_FIXTURE_PATH = (
    _PROJECT_ROOT
    / "data"
    / "gold_standard"
    / "Samsara_Inc_8K_2025-08-21"
    / "filing.html"
)

# Sentinel written by the filing fetcher between primary cover page and exhibit.
_EXHIBIT_SEPARATOR = "<!-- EXHIBIT-99.1 -->"

# Minimum HTML size (bytes) below which the pipeline silently returns no facts.
# See feedback_zero_facts_can_be_pre_pipeline_failure.
_MIN_FIXTURE_SIZE_BYTES = 15_000

# Synthetic filing_id — no DB connection required.
_SYNTHETIC_FILING_ID = 88888

# ---------------------------------------------------------------------------
# Pre-flight helper
# ---------------------------------------------------------------------------


def _assert_fixture_ok() -> None:
    """
    Confirm the fixture file is present and sane before running pipeline tests.

    Called once at fixture-setup time so that a missing or undersized fixture
    produces a pytest.skip rather than a confusing assertion failure from the
    pipeline itself.
    """
    if not _FIXTURE_PATH.exists():
        pytest.skip(f"8-K exhibit fixture not found at {_FIXTURE_PATH}")

    size = _FIXTURE_PATH.stat().st_size
    if size < _MIN_FIXTURE_SIZE_BYTES:
        pytest.skip(
            f"8-K exhibit fixture is only {size} bytes; "
            f"must be >= {_MIN_FIXTURE_SIZE_BYTES} to clear pipeline size gate. "
            f"Path: {_FIXTURE_PATH}"
        )

    content = _FIXTURE_PATH.read_text(encoding="utf-8")

    # Verify the exhibit separator is present — if it's missing the fixture
    # does not represent a properly-concatenated 8-K + exhibit file.
    assert _EXHIBIT_SEPARATOR in content, (
        f"Fixture at {_FIXTURE_PATH} does not contain the exhibit separator "
        f"{_EXHIBIT_SEPARATOR!r}. The fixture must be a combined primary+exhibit HTML."
    )

    # Verify exhibit-sourced language is actually present.
    content_lower = content.lower()
    assert "total revenue" in content_lower, (
        f"Fixture at {_FIXTURE_PATH} does not contain 'total revenue'. "
        "The exhibit section may be missing."
    )
    assert "arr" in content_lower, (
        f"Fixture at {_FIXTURE_PATH} does not contain 'ARR'. "
        "The exhibit section may be missing."
    )


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def eight_k_result() -> PipelineResult:
    """
    Run the V2 pipeline on the Samsara 8-K exhibit fixture once per test session.

    Skips the entire test class if the fixture is absent or undersized.
    Images are disabled (no OPENAI_API_KEY in CI).
    """
    _assert_fixture_ok()
    config = PipelineConfig(
        enable_image_extraction=False,
        enable_chart_extraction=False,
        enable_section_classification=True,
        min_confidence_auto_accept=0.90,
    )
    return process_filing(
        html_path=_FIXTURE_PATH,
        filing_id=_SYNTHETIC_FILING_ID,
        config=config,
        cik="0001642545",
        accession_number="0001642545-25-000312",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEightKExhibitE2EPipeline:
    """
    End-to-end pipeline tests for 8-K exhibit content extraction (legacy-116).

    These tests assert that a combined 8-K HTML (primary cover + exhibit 99.1)
    is processed by the V2 pipeline and that:
      (i)  segment count is non-trivial (> 20), confirming the exhibit is
           being parsed rather than silently discarded.
      (ii) at least one MetricFact is produced from exhibit-sourced language
           ("total revenue" or "ARR"), confirming metric extraction reaches
           the exhibit section.
    """

    def test_fixture_content_sanity(self) -> None:
        """
        Fixture pre-flight: confirm file exists, is > 15 KB, and contains
        the exhibit separator + expected content strings.

        Fails fast with a descriptive message if the fixture is broken,
        so subsequent tests produce clear skips rather than misleading errors.
        Per feedback_zero_facts_can_be_pre_pipeline_failure.
        """
        _assert_fixture_ok()

    def test_pipeline_succeeds(self, eight_k_result: PipelineResult) -> None:
        """Pipeline must report success=True on the exhibit fixture."""
        assert eight_k_result.success, (
            f"Pipeline failed: {eight_k_result.error_message}. "
            "Check that the fixture is valid HTML and the pipeline config is correct."
        )
        assert eight_k_result.document is not None, "result.document is None after successful run"
        assert eight_k_result.total_duration_ms > 0

    def test_segment_count_exceeds_threshold(self, eight_k_result: PipelineResult) -> None:
        """
        At least 20 segments must be produced.

        A count <= 20 would indicate the exhibit HTML (after the separator) is
        not being ingested by the segmentation stage, or the fixture is being
        short-circuited at the size-gate level.
        """
        assert eight_k_result.success
        segment_count = len(eight_k_result.segments)
        assert segment_count > 20, (
            f"Only {segment_count} segments extracted from 8-K exhibit fixture. "
            "Expected > 20. The exhibit section may not be reaching segmentation. "
            f"Fixture path: {_FIXTURE_PATH}"
        )

    def test_exhibit_metric_fact_extracted(self, eight_k_result: PipelineResult) -> None:
        """
        At least one MetricFact must be produced whose evidence snippet
        contains exhibit-sourced language: 'total revenue', 'arr',
        'annual recurring revenue', or 'retention'.

        This assertion verifies the full pipeline path from segmentation through
        candidate generation, value binding, and fact construction for content
        that lives after the <!-- EXHIBIT-99.1 --> separator.
        """
        assert eight_k_result.success
        assert eight_k_result.fact_count > 0, (
            f"No MetricFacts extracted from 8-K exhibit fixture. "
            f"Segments parsed: {len(eight_k_result.segments)}. "
            "The exhibit content may not be reaching candidate generation."
        )

        exhibit_keywords = ("total revenue", "arr", "annual recurring revenue", "retention")
        matching_facts = []
        for fact in eight_k_result.facts:
            snippet = (fact.evidence_pack.snippet_html or "").lower()
            context_before = (fact.evidence_pack.context_before or "").lower()
            context_after = (fact.evidence_pack.context_after or "").lower()
            combined = snippet + " " + context_before + " " + context_after
            if any(kw in combined for kw in exhibit_keywords):
                matching_facts.append(fact)

        assert len(matching_facts) > 0, (
            f"No MetricFacts found with exhibit-sourced language "
            f"({exhibit_keywords!r}) in their evidence_pack. "
            f"Total facts extracted: {eight_k_result.fact_count}. "
            f"First 3 fact metric IDs: "
            f"{[f.canonical_metric_id for f in eight_k_result.facts[:3]]}. "
            "The exhibit section may be parsed but metric extraction may not be "
            "reaching those segments."
        )

    def test_exhibit_facts_have_valid_provenance(self, eight_k_result: PipelineResult) -> None:
        """Every MetricFact extracted must have valid provenance (source_locator)."""
        assert eight_k_result.success

        if eight_k_result.fact_count == 0:
            pytest.skip("No facts extracted — provenance check requires at least one fact")

        for fact in eight_k_result.facts:
            assert fact.source_locator is not None, (
                f"Fact {fact.fact_id} ({fact.canonical_metric_id}) missing source_locator"
            )
            has_location = (
                fact.source_locator.dom_locator is not None
                or fact.source_locator.segment_id is not None
                or fact.source_locator.table_id is not None
                or fact.source_locator.img_id is not None
            )
            assert has_location, (
                f"Fact {fact.fact_id} ({fact.canonical_metric_id}) has no "
                "dom_locator, segment_id, table_id, or img_id in source_locator"
            )
            assert fact.evidence_pack is not None, (
                f"Fact {fact.fact_id} ({fact.canonical_metric_id}) missing evidence_pack"
            )
            assert fact.evidence_pack.snippet_html, (
                f"Fact {fact.fact_id} ({fact.canonical_metric_id}) has empty snippet_html"
            )

    def test_exhibit_fact_metric_ids_valid(self, eight_k_result: PipelineResult) -> None:
        """Every extracted MetricFact must have a canonical_metric_id starting with 'cm_'."""
        assert eight_k_result.success

        if eight_k_result.fact_count == 0:
            pytest.skip("No facts extracted — metric ID check requires at least one fact")

        bad_ids = [
            f.canonical_metric_id
            for f in eight_k_result.facts
            if not f.canonical_metric_id.startswith("cm_")
        ]
        assert not bad_ids, (
            f"Facts with invalid metric IDs (not starting with 'cm_'): {bad_ids[:5]}"
        )
