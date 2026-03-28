"""
Transcript Gold Standard Regression Tests.

Evaluates V2 pipeline performance on manually annotated earnings call transcripts.
Checks recall/precision/F1 against a saved baseline and absolute floor thresholds.

Scope controlled by --transcript-split (default: tuning).
Baseline updated by --transcript-update-baseline.

Run:
    pytest -m transcript_gold_standard -v
    pytest -m transcript_gold_standard --transcript-split test -v
    pytest -m transcript_gold_standard --transcript-update-baseline -v
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.transcript_gold_standard, pytest.mark.integration]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_GS_DIR = _PROJECT_ROOT / "data" / "transcript_gold_standard"
_GOLD_STANDARD_CSV = _GS_DIR / "transcript_gold_standard.csv"
_SPLIT_JSON = _GS_DIR / "split.json"
_HTML_DIR = _PROJECT_ROOT / "data" / "spike_samples" / "transcripts_html"

# Minimum expected annotations for a complete gold standard
_MIN_ANNOTATION_COUNT = 90

# Regression tolerance: 1 percentage point
_REGRESSION_TOLERANCE = 0.01

# Absolute floor thresholds (independent of baseline)
_FLOOR_RECALL = 0.40
_FLOOR_PRECISION = 0.50
_FLOOR_F1 = 0.45


# ---------------------------------------------------------------------------
# Import matching/scoring helpers from validate_transcript_extraction script
# ---------------------------------------------------------------------------


def _load_validator_module():
    """Load validate_transcript_extraction.py via importlib to reuse matching logic."""
    script_path = _PROJECT_ROOT / "scripts" / "validate_transcript_extraction.py"
    spec = importlib.util.spec_from_file_location("validate_transcript_extraction", script_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_vte = _load_validator_module()


# ---------------------------------------------------------------------------
# Module-scoped pipeline run fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def transcript_extraction_scores(transcript_split):
    """
    Run the V2 pipeline on all HTML transcripts for the selected split.

    Returns (agg_scores, per_company_scores) as a tuple.
    Skips if HTML transcript files or gold standard are missing.
    """
    if not _GOLD_STANDARD_CSV.exists():
        pytest.skip(
            f"Gold standard CSV not found: {_GOLD_STANDARD_CSV}. "
            "Run Phase 2 annotation workflow first."
        )

    html_files = sorted(_HTML_DIR.glob("*.html"))
    if not html_files:
        pytest.skip(
            f"No HTML transcript files found in {_HTML_DIR}. "
            "Run scripts/spike/convert_transcript_to_html.py first."
        )

    # Resolve split_filter: 'all' maps to None (no filter)
    split_filter = None if transcript_split == "all" else transcript_split

    annotations = _vte.load_annotations(_GOLD_STANDARD_CSV, split_filter=split_filter)
    if not annotations:
        pytest.skip(
            f"No annotations loaded for split='{transcript_split}'. "
            "Check split.json and gold standard CSV."
        )

    # Filter HTML files to tickers with annotations (for split-aware evaluation)
    if split_filter:
        annotated_tickers = {key.split("_")[0] for key in annotations}
        html_files = [f for f in html_files if f.stem.split("_")[0] in annotated_tickers]
        if not html_files:
            pytest.skip(f"No HTML files match {split_filter} split tickers.")

    results = _vte.run_validation(html_files, annotations)
    agg = _vte.aggregate_scores(results)
    per_company = _vte.per_company_scores(results)

    return agg, per_company, results


# ---------------------------------------------------------------------------
# TestTranscriptGoldStandardData
# ---------------------------------------------------------------------------


class TestTranscriptGoldStandardData:
    """Data integrity checks — verify the gold standard exists and is populated."""

    def test_gold_standard_csv_exists(self):
        """Gold standard CSV must exist after annotation workflow is complete."""
        assert _GOLD_STANDARD_CSV.exists(), (
            f"Gold standard CSV not found: {_GOLD_STANDARD_CSV}. "
            "Run Phase 2 annotation workflow (merge_transcript_annotations.py)."
        )

    def test_split_json_exists(self):
        """split.json must exist to support tuning/test split evaluation."""
        assert _SPLIT_JSON.exists(), (
            f"split.json not found: {_SPLIT_JSON}. "
            "Run merge_transcript_annotations.py to generate it."
        )

    def test_minimum_annotation_count(self):
        """Gold standard must have at least 100 annotations for meaningful evaluation."""
        if not _GOLD_STANDARD_CSV.exists():
            pytest.skip("Gold standard CSV not found — run test_gold_standard_csv_exists first.")

        import csv

        with open(_GOLD_STANDARD_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) >= _MIN_ANNOTATION_COUNT, (
            f"Gold standard has only {len(rows)} annotations; "
            f"expected >= {_MIN_ANNOTATION_COUNT}. "
            "Annotation workflow may be incomplete."
        )

    def test_split_json_has_tuning_and_test(self):
        """split.json must contain both tuning and test assignments."""
        if not _SPLIT_JSON.exists():
            pytest.skip("split.json not found.")

        doc = json.loads(_SPLIT_JSON.read_text())
        assert doc.get("tuning_companies"), "split.json has no tuning_companies"
        assert doc.get("test_companies"), "split.json has no test_companies"


# ---------------------------------------------------------------------------
# TestTranscriptGoldStandardFloors
# ---------------------------------------------------------------------------


class TestTranscriptGoldStandardFloors:
    """Absolute minimum performance floors — independent of baseline."""

    def test_recall_floor(self, transcript_extraction_scores):
        """Recall must be at least 40% on the selected split."""
        agg, _, _ = transcript_extraction_scores
        recall = agg["recall"]
        assert recall >= _FLOOR_RECALL, (
            f"Recall {recall:.1%} is below absolute floor of {_FLOOR_RECALL:.0%}. "
            "Pipeline performance is unacceptably low on transcripts."
        )

    def test_precision_floor(self, transcript_extraction_scores):
        """Precision must be at least 50% on the selected split."""
        agg, _, _ = transcript_extraction_scores
        precision = agg["precision"]
        assert precision >= _FLOOR_PRECISION, (
            f"Precision {precision:.1%} is below absolute floor of {_FLOOR_PRECISION:.0%}."
        )

    def test_f1_floor(self, transcript_extraction_scores):
        """F1 must be at least 45% on the selected split."""
        agg, _, _ = transcript_extraction_scores
        f1 = agg["f1"]
        assert f1 >= _FLOOR_F1, (
            f"F1 {f1:.1%} is below absolute floor of {_FLOOR_F1:.0%}."
        )


# ---------------------------------------------------------------------------
# TestTranscriptGoldStandardRegression
# ---------------------------------------------------------------------------


class TestTranscriptGoldStandardRegression:
    """Baseline regression tests — fail if metrics drop more than 1pp from baseline."""

    def test_recall_above_baseline(self, transcript_extraction_scores, transcript_baseline):
        """Recall must not drop more than 1pp below the saved baseline."""
        if transcript_baseline is None:
            pytest.skip("No baseline saved. Run with --transcript-update-baseline first.")

        agg, _, _ = transcript_extraction_scores
        current = agg["recall"]
        base = transcript_baseline["aggregate"]["recall"]
        delta = current - base

        assert delta >= -_REGRESSION_TOLERANCE, (
            f"Recall regression: {current:.1%} (was {base:.1%}, delta {delta:+.1%}). "
            "Review changes before merging."
        )

    def test_precision_above_baseline(self, transcript_extraction_scores, transcript_baseline):
        """Precision must not drop more than 1pp below the saved baseline."""
        if transcript_baseline is None:
            pytest.skip("No baseline saved. Run with --transcript-update-baseline first.")

        agg, _, _ = transcript_extraction_scores
        current = agg["precision"]
        base = transcript_baseline["aggregate"]["precision"]
        delta = current - base

        assert delta >= -_REGRESSION_TOLERANCE, (
            f"Precision regression: {current:.1%} (was {base:.1%}, delta {delta:+.1%}). "
            "Review changes before merging."
        )

    def test_f1_above_baseline(self, transcript_extraction_scores, transcript_baseline):
        """F1 must not drop more than 1pp below the saved baseline."""
        if transcript_baseline is None:
            pytest.skip("No baseline saved. Run with --transcript-update-baseline first.")

        agg, _, _ = transcript_extraction_scores
        current = agg["f1"]
        base = transcript_baseline["aggregate"]["f1"]
        delta = current - base

        assert delta >= -_REGRESSION_TOLERANCE, (
            f"F1 regression: {current:.1%} (was {base:.1%}, delta {delta:+.1%}). "
            "Review changes before merging."
        )

    def test_no_company_recall_collapse(self, transcript_extraction_scores):
        """No individual company should have 0% recall (complete extraction failure)."""
        _, per_company, _ = transcript_extraction_scores
        collapsed = [
            ticker
            for ticker, scores in per_company.items()
            if scores.get("recall", 1.0) == 0.0 and scores.get("total_annotations", 0) > 0
        ]
        assert not collapsed, (
            f"Companies with 0% recall: {sorted(collapsed)}. "
            "Extraction completely failed for these tickers."
        )


# ---------------------------------------------------------------------------
# TestTranscriptBaselineUpdate
# ---------------------------------------------------------------------------


class TestTranscriptBaselineUpdate:
    """Saves current results as the new baseline when --transcript-update-baseline is set."""

    def test_update_baseline(
        self,
        transcript_extraction_scores,
        transcript_baseline_path,
        transcript_update_baseline,
        transcript_split,
    ):
        """Save the current extraction results as the new baseline."""
        if not transcript_update_baseline:
            pytest.skip("Pass --transcript-update-baseline to update the baseline.")

        agg, per_company, results = transcript_extraction_scores

        from datetime import datetime

        baseline_data = {
            "timestamp": datetime.now().isoformat(),
            "split": transcript_split,
            "annotations_source": str(_GOLD_STANDARD_CSV),
            "aggregate": agg,
            "per_company": per_company,
        }

        transcript_baseline_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_baseline_path.write_text(json.dumps(baseline_data, indent=2))

        print(f"\n  Baseline saved to: {transcript_baseline_path}")
        print(f"  Recall: {agg['recall']:.1%}, Precision: {agg['precision']:.1%}, F1: {agg['f1']:.1%}")
