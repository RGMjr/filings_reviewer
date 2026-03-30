"""Unit tests for scripts/export_image_decisions.py."""

import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.export_image_decisions import (
    OUTPUT_COLUMNS,
    export_decisions,
    format_decision_row,
    main,
    write_csv,
    write_json,
)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_DB_ROWS = [
    {
        "image_decision_id": 1,
        "image_candidate_id": 10,
        "decision": "relevant",
        "chart_type": "cohort_parfait",
        "rejection_reason": None,
        "reviewer_notes": "test notes",
        "reviewer_id": "user1",
        "review_time_seconds": 30,
        "created_at": "2026-03-15 10:00:00",
        "filing_id": 5,
        "image_src": "/images/chart1.png",
        "image_url": "https://example.com/chart1.png",
        "image_width": 800,
        "image_height": 600,
        "detection_tier": "tier_1_cohort",
        "cohort_confidence": 0.85,
        "accession_number": "0001234567-20-000001",
        "company_name": "Test Corp",
    }
]


# ---------------------------------------------------------------------------
# format_decision_row tests
# ---------------------------------------------------------------------------


def test_format_decision_row_keys_match_output_columns():
    result = format_decision_row(SAMPLE_DB_ROWS[0], "Test Corp")
    assert set(result.keys()) == set(OUTPUT_COLUMNS)


def test_format_decision_row_decision_date_truncated():
    result = format_decision_row(SAMPLE_DB_ROWS[0], "Test Corp")
    assert result["decision_date"] == "2026-03-15"


# ---------------------------------------------------------------------------
# export_decisions tests
# ---------------------------------------------------------------------------


def test_export_decisions_all_status():
    mock_db = MagicMock()
    mock_db.query.return_value = SAMPLE_DB_ROWS

    result = export_decisions(mock_db, status="all")

    mock_db.query.assert_called_once()
    assert len(result) == 1
    # "all" status should NOT add a decision= filter to the SQL
    sql_called = mock_db.query.call_args[0][0]
    assert "decision =" not in sql_called


def test_export_decisions_relevant_filter():
    mock_db = MagicMock()
    mock_db.query.return_value = SAMPLE_DB_ROWS

    export_decisions(mock_db, status="relevant")

    sql_called = mock_db.query.call_args[0][0]
    assert "relevant" in sql_called


def test_export_decisions_not_relevant_filter():
    mock_db = MagicMock()
    mock_db.query.return_value = SAMPLE_DB_ROWS

    export_decisions(mock_db, status="not_relevant")

    sql_called = mock_db.query.call_args[0][0]
    assert "not_relevant" in sql_called


def test_export_decisions_filing_id_filter():
    mock_db = MagicMock()
    mock_db.query.return_value = SAMPLE_DB_ROWS

    export_decisions(mock_db, filing_id=5)

    params = mock_db.query.call_args[0][1]
    assert params == {"filing_id": 5}


def test_export_decisions_tier_filter():
    mock_db = MagicMock()
    mock_db.query.return_value = SAMPLE_DB_ROWS

    export_decisions(mock_db, detection_tier="tier_1_cohort")

    params = mock_db.query.call_args[0][1]
    assert params == {"detection_tier": "tier_1_cohort"}


# ---------------------------------------------------------------------------
# write_csv tests
# ---------------------------------------------------------------------------


def test_write_csv_header_matches_output_columns():
    formatted_row = format_decision_row(SAMPLE_DB_ROWS[0], "Test Corp")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = Path(f.name)

    try:
        write_csv([formatted_row], output_path=path)
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == OUTPUT_COLUMNS
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# write_json tests
# ---------------------------------------------------------------------------


def test_write_json_structure():
    formatted_row = format_decision_row(SAMPLE_DB_ROWS[0], "Test Corp")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = Path(f.name)

    try:
        write_json([formatted_row], output_path=path)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1
        assert set(data[0].keys()) == set(OUTPUT_COLUMNS)
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# main() tests
# ---------------------------------------------------------------------------


def test_main_no_database_url_exits():
    with patch.dict(os.environ, {}, clear=True):
        with patch("sys.argv", ["export_image_decisions.py"]):
            with patch("scripts.export_image_decisions.load_dotenv"):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
