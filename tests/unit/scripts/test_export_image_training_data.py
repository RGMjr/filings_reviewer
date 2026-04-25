"""Unit tests for scripts/export_image_training_data.py — keyword-count fix (Wave A1).

Specifically validates that export_sec_rows() emits real keyword_count /
detected_keywords values derived from nearby_text, not hardcoded zeros.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "export_image_training_data.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("export_image_training_data", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, (
        f"Could not load module from {_SCRIPT_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    # Pre-populate sys.path so the script's `sys.path.insert` succeeds for src imports
    root = str(_SCRIPT_PATH.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db(rows: list[dict]) -> MagicMock:
    mock_db = MagicMock()
    mock_db.query.return_value = rows
    return mock_db


def _base_sec_row(**overrides: Any) -> dict:
    base: dict = {
        "img_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "decision": "relevant",
        "chart_type": "cohort_table",
        "rejection_reason": None,
        "filename": "chart1.png",
        "width": 800,
        "height": 600,
        "nearby_text": "",
        "classification": "chart",
        "section_type": "MD&A",
        "relevance_score": 0.5,
        "accession_number": "0001234567-23-000001",
        "company_name": "Acme Corp",
        "image_url": "https://www.sec.gov/Archives/edgar/data/1/0001234567-23-000001/chart1.png",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# COHORT_KEYWORDS constant
# ---------------------------------------------------------------------------


def test_cohort_keywords_constant_exists() -> None:
    mod = _load_module()
    assert hasattr(mod, "COHORT_KEYWORDS"), "COHORT_KEYWORDS module-level constant missing"
    assert isinstance(mod.COHORT_KEYWORDS, set)
    assert len(mod.COHORT_KEYWORDS) > 0


def test_cohort_keywords_contains_expected_terms() -> None:
    mod = _load_module()
    for term in ("cohort", "retention", "ltv", "cac", "arr", "mrr", "nrr", "vintage"):
        assert term in mod.COHORT_KEYWORDS, f"'{term}' missing from COHORT_KEYWORDS"


# ---------------------------------------------------------------------------
# export_sec_rows: keyword_count and detected_keywords
# ---------------------------------------------------------------------------


def test_sec_rows_no_keywords_when_nearby_text_empty() -> None:
    mod = _load_module()
    row = _base_sec_row(nearby_text="", relevance_score=0.0)
    result = mod.export_sec_rows(_make_mock_db([row]))
    assert len(result) == 1
    assert result[0]["keyword_count"] == 0
    assert result[0]["detected_keywords"] == ""


def test_sec_rows_single_keyword_detected() -> None:
    mod = _load_module()
    row = _base_sec_row(nearby_text="Here we show the cohort performance over time.")
    result = mod.export_sec_rows(_make_mock_db([row]))
    assert result[0]["keyword_count"] == 1
    assert "cohort" in result[0]["detected_keywords"]


def test_sec_rows_multiple_keywords_detected() -> None:
    mod = _load_module()
    row = _base_sec_row(nearby_text="Retention rates and cohort LTV show strong CAC payback.")
    result = mod.export_sec_rows(_make_mock_db([row]))
    # Expect retention, cohort, ltv, cac — at minimum > 1
    assert result[0]["keyword_count"] >= 2
    keywords = result[0]["detected_keywords"].split(",")
    assert "retention" in keywords
    assert "cohort" in keywords


def test_sec_rows_detected_keywords_sorted() -> None:
    """detected_keywords must be a deterministic sorted comma-separated string."""
    mod = _load_module()
    row = _base_sec_row(nearby_text="MRR, ARR, NRR and retention are tracked monthly.")
    result = mod.export_sec_rows(_make_mock_db([row]))
    kws = result[0]["detected_keywords"].split(",")
    assert kws == sorted(kws), "detected_keywords must be sorted"


def test_sec_rows_keyword_count_matches_detected_keywords_length() -> None:
    mod = _load_module()
    row = _base_sec_row(nearby_text="Annual Recurring Revenue (ARR) and NRR cohort data.")
    result = mod.export_sec_rows(_make_mock_db([row]))
    detected = [k for k in result[0]["detected_keywords"].split(",") if k]
    assert result[0]["keyword_count"] == len(detected)


def test_sec_rows_no_longer_hardcodes_zero() -> None:
    """Regression guard: a row with keyword-rich nearby_text must NOT produce keyword_count=0."""
    mod = _load_module()
    row = _base_sec_row(nearby_text="Cohort retention improved; LTV/CAC ratio expanded.")
    result = mod.export_sec_rows(_make_mock_db([row]))
    assert result[0]["keyword_count"] != 0, (
        "keyword_count must not be hardcoded to 0 when nearby_text contains keywords"
    )
    assert result[0]["detected_keywords"] != "", (
        "detected_keywords must not be hardcoded to empty string when nearby_text contains keywords"
    )


# ---------------------------------------------------------------------------
# export_sec_rows: cohort_keyword_nearby logic
# ---------------------------------------------------------------------------


def test_cohort_keyword_nearby_set_by_keyword_match() -> None:
    """cohort_keyword_nearby should be 1 when keywords detected, regardless of score."""
    mod = _load_module()
    row = _base_sec_row(nearby_text="Retention cohort analysis.", relevance_score=0.0)
    result = mod.export_sec_rows(_make_mock_db([row]))
    assert result[0]["cohort_keyword_nearby"] == 1


def test_cohort_keyword_nearby_fallback_to_relevance_score() -> None:
    """cohort_keyword_nearby should still be 1 when no keywords but score >= 0.6."""
    mod = _load_module()
    row = _base_sec_row(nearby_text="No relevant terms here.", relevance_score=0.75)
    result = mod.export_sec_rows(_make_mock_db([row]))
    assert result[0]["cohort_keyword_nearby"] == 1


def test_cohort_keyword_nearby_zero_when_neither() -> None:
    mod = _load_module()
    row = _base_sec_row(nearby_text="Some random text.", relevance_score=0.2)
    result = mod.export_sec_rows(_make_mock_db([row]))
    assert result[0]["cohort_keyword_nearby"] == 0


# ---------------------------------------------------------------------------
# Case-insensitivity
# ---------------------------------------------------------------------------


def test_sec_rows_keyword_detection_case_insensitive() -> None:
    mod = _load_module()
    row = _base_sec_row(nearby_text="COHORT retention LTV analysis.")
    result = mod.export_sec_rows(_make_mock_db([row]))
    assert result[0]["keyword_count"] >= 1
    # At least "cohort" should be detected via lowercasing
    assert "cohort" in result[0]["detected_keywords"]


# ---------------------------------------------------------------------------
# Presentation path: ensure COHORT_KEYWORDS is now used (pres path unchanged)
# ---------------------------------------------------------------------------


def test_pres_export_uses_same_cohort_keywords_constant() -> None:
    """Verify export_pres_rows still works and uses module-level COHORT_KEYWORDS."""
    mod = _load_module()
    # The presentation export reads from disk; just confirm the function is importable
    # and that COHORT_KEYWORDS is not re-defined inline (we can't easily test the full
    # pres path without fixture files, but we can inspect the constant is shared).
    import inspect

    src = inspect.getsource(mod.export_pres_rows)
    # The old inline definition must not exist
    assert "cohort_keywords = {" not in src, (
        "export_pres_rows must not re-define cohort_keywords locally; use COHORT_KEYWORDS"
    )


# ---------------------------------------------------------------------------
# export_sec_rows: legacy + confirmations UNION + dedup (gh-196)
# ---------------------------------------------------------------------------


def _make_two_query_mock_db(legacy: list[dict], confirmations: list[dict]) -> MagicMock:
    """Mock that returns `legacy` on the first .query() call and `confirmations` on the second."""
    mock_db = MagicMock()
    mock_db.query.side_effect = [legacy, confirmations]
    return mock_db


def test_sec_rows_emits_legacy_and_confirmation_rows() -> None:
    mod = _load_module()
    legacy_row = _base_sec_row(img_id="11111111-1111-1111-1111-111111111111")
    confirmation_row = _base_sec_row(
        img_id="22222222-2222-2222-2222-222222222222",
        chart_type=None,
        decision="not_relevant",
        rejection_reason="not_present",
    )
    result = mod.export_sec_rows(_make_two_query_mock_db([legacy_row], [confirmation_row]))
    assert len(result) == 2
    by_img = {r["image_id"]: r for r in result}
    assert "sec:11111111-1111-1111-1111-111111111111" in by_img
    assert "sec:22222222-2222-2222-2222-222222222222" in by_img


def test_sec_rows_legacy_takes_precedence_on_duplicate_img_id() -> None:
    """If an img_id appears in both surfaces, the legacy row wins."""
    mod = _load_module()
    legacy_row = _base_sec_row(decision="relevant", chart_type="cohort_table")
    # Same img_id, different decision shape
    confirmation_row = _base_sec_row(decision="not_relevant", chart_type=None)
    result = mod.export_sec_rows(_make_two_query_mock_db([legacy_row], [confirmation_row]))
    assert len(result) == 1
    assert result[0]["decision"] == "relevant"
    assert result[0]["chart_type"] == "cohort_table"


def test_sec_rows_handles_null_chart_type_from_confirmations() -> None:
    """Confirmation-derived rows have chart_type=None; downstream emits ''."""
    mod = _load_module()
    confirmation_row = _base_sec_row(
        img_id="33333333-3333-3333-3333-333333333333",
        chart_type=None,
        decision="relevant",
    )
    result = mod.export_sec_rows(_make_two_query_mock_db([], [confirmation_row]))
    assert len(result) == 1
    # The transform path coerces None to '' for CSV emission
    assert result[0]["chart_type"] == ""
