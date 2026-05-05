"""Unit tests for scripts/check_stalled_runs.py formatting logic."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

# Load the script module without executing main()
_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_stalled_runs.py"
spec = importlib.util.spec_from_file_location("check_stalled_runs", _SCRIPT)
_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(_mod)  # type: ignore[union-attr]

format_stall_section = _mod.format_stall_section
_fmt_ts = _mod._fmt_ts


class TestFmtTs:
    def test_none_returns_unknown(self):
        assert _fmt_ts(None) == "unknown"

    def test_aware_datetime_formatted(self):
        ts = datetime(2026, 5, 5, 6, 30, 0, tzinfo=UTC)
        assert _fmt_ts(ts) == "2026-05-05 06:30 UTC"

    def test_naive_datetime_treated_as_utc(self):
        ts = datetime(2026, 5, 5, 6, 30, 0)
        assert _fmt_ts(ts) == "2026-05-05 06:30 UTC"


class TestFormatStallSectionAllClear:
    def test_returns_empty_string_when_no_stalls(self):
        assert format_stall_section([], [], []) == ""


class TestFormatStallSectionTextRows:
    def _make_text_row(self, id="abc123", triggered_by="RGM"):
        return {
            "id": id,
            "started_at": datetime(2026, 5, 5, 5, 0, 0, tzinfo=UTC),
            "triggered_by": triggered_by,
        }

    def test_section_header_present(self):
        section = format_stall_section([self._make_text_row()], [], [])
        assert "## Stalled runs (1 detected)" in section

    def test_text_subsection_header(self):
        section = format_stall_section([self._make_text_row()], [], [])
        assert "### text_decision_analysis_runs (1)" in section

    def test_row_id_and_triggered_by(self):
        section = format_stall_section(
            [self._make_text_row(id="zzz999", triggered_by="alice")], [], []
        )
        assert "zzz999" in section
        assert "alice" in section

    def test_null_triggered_by_shows_unknown(self):
        section = format_stall_section([self._make_text_row(triggered_by=None)], [], [])
        assert "unknown" in section

    def test_manual_fix_hint_present(self):
        section = format_stall_section([self._make_text_row()], [], [])
        assert "text_decision_analysis_runs" in section
        assert "manual cleanup" in section

    def test_two_rows_both_listed(self):
        rows = [self._make_text_row(id="a1"), self._make_text_row(id="b2")]
        section = format_stall_section(rows, [], [])
        assert "a1" in section
        assert "b2" in section
        assert "## Stalled runs (2 detected)" in section


class TestFormatStallSectionModelRows:
    def _make_model_row(self, id="m1", model_type="image_relevance"):
        return {
            "id": id,
            "started_at": datetime(2026, 5, 5, 4, 0, 0, tzinfo=UTC),
            "run_lock_until": datetime(2026, 5, 5, 4, 30, 0, tzinfo=UTC),
            "model_type": model_type,
        }

    def test_model_subsection_header(self):
        section = format_stall_section([], [self._make_model_row()], [])
        assert "### model_training_runs (1)" in section

    def test_model_type_and_lock_ts_present(self):
        section = format_stall_section([], [self._make_model_row()], [])
        assert "image_relevance" in section
        assert "2026-05-05 04:30 UTC" in section

    def test_manual_fix_hint_present(self):
        section = format_stall_section([], [self._make_model_row()], [])
        assert "model_training_runs" in section
        assert "manual cleanup" in section


class TestFormatStallSectionBatchRows:
    def _make_batch_row(self, batch_id="batch-1"):
        return {
            "batch_id": batch_id,
            "started_at": datetime(2026, 5, 5, 3, 0, 0, tzinfo=UTC),
            "run_lock_until": datetime(2026, 5, 5, 3, 30, 0, tzinfo=UTC),
        }

    def test_batch_subsection_header(self):
        section = format_stall_section([], [], [self._make_batch_row()])
        assert "### v2_ingest_batches (1)" in section

    def test_batch_id_present(self):
        section = format_stall_section([], [], [self._make_batch_row(batch_id="batch-999")])
        assert "batch-999" in section

    def test_resume_hint_present(self):
        section = format_stall_section([], [], [self._make_batch_row()])
        assert "resume" in section.lower()


class TestFormatStallSectionMixed:
    def test_total_count_sums_all_tables(self):
        text_row = {"id": "t1", "started_at": datetime(2026, 5, 5, tzinfo=UTC), "triggered_by": "a"}
        model_row = {
            "id": "m1",
            "started_at": datetime(2026, 5, 5, tzinfo=UTC),
            "run_lock_until": datetime(2026, 5, 5, tzinfo=UTC),
            "model_type": "image_relevance",
        }
        batch_row = {
            "batch_id": "b1",
            "started_at": datetime(2026, 5, 5, tzinfo=UTC),
            "run_lock_until": datetime(2026, 5, 5, tzinfo=UTC),
        }
        section = format_stall_section([text_row], [model_row], [batch_row])
        assert "## Stalled runs (3 detected)" in section

    def test_persistent_rows_note_present(self):
        text_row = {"id": "t1", "started_at": datetime(2026, 5, 5, tzinfo=UTC), "triggered_by": "a"}
        section = format_stall_section([text_row], [], [])
        assert "permanently stuck worker" in section
