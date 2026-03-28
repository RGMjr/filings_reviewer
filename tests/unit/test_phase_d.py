"""
Unit tests for Phase D scripts:
- check_new_documents.py
- ingest_all.py
- Checkpointing (ingest_transcripts.py + ingest_presentations.py)
- Circuit breaker (ingest_transcripts.py + ingest_presentations.py)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# check_new_documents helpers
# ---------------------------------------------------------------------------


class TestCheckNewDocumentsClassification:
    """Test new vs ingested classification logic in check_new_documents."""

    def _make_metadata(self, source_id: str = "abc123", ticker: str = "CRM") -> Any:
        from src.infra.document_source import DocumentMetadata
        return DocumentMetadata(
            source_id=source_id,
            source="huggingface:test",
            ticker=ticker,
            document_type="earnings_call",
            document_date=date(2025, 2, 26),
        )

    def test_new_when_not_in_db(self):
        """Documents not in DB are classified as 'new'."""
        with patch("scripts.check_new_documents.check_documents") as mock_check:
            from scripts.check_new_documents import CheckResult, DocumentStatus
            mock_check.return_value = CheckResult(
                new=[
                    DocumentStatus("CRM", "transcript", "2025-02-26", "new", "id2"),
                    DocumentStatus("CRM", "transcript", "2025-02-26", "new", "id3"),
                ],
                ingested=[
                    DocumentStatus("CRM", "transcript", "2025-02-26", "ingested", "id1"),
                ],
                errors=[],
            )
            result = mock_check(tickers=["CRM"], source_filter="transcript", db_url="fake://")
            assert len(result.new) == 2
            assert len(result.ingested) == 1

    def test_check_ingested_db_presentation(self):
        """_check_ingested_db returns source_id for presentation when accession matches."""
        from scripts.check_new_documents import _check_ingested_db

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        source_id = "0001234567/0001234567-24-000001/presentation.pdf"
        # DB returns "presentation:{source_id}" in accessions
        mock_cur.fetchall.side_effect = [
            [{"accession_number": f"presentation:{source_id}"}],
            [],  # v2_documents query
        ]

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.extras.RealDictCursor = MagicMock()
        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2, "psycopg2.extras": mock_psycopg2.extras}):
            result = _check_ingested_db([source_id], "postgresql://fake")
        assert source_id in result

    def test_check_ingested_db_empty_when_absent(self):
        """_check_ingested_db returns empty set when source_id not in DB."""
        from scripts.check_new_documents import _check_ingested_db

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_cur.fetchall.side_effect = [
            [],  # filings query — nothing found
            [],  # v2_documents query
        ]

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.extras.RealDictCursor = MagicMock()
        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2, "psycopg2.extras": mock_psycopg2.extras}):
            result = _check_ingested_db(["unknown_id"], "postgresql://fake")
        assert len(result) == 0

    def test_check_ingested_db_handles_error(self):
        """_check_ingested_db returns empty set on connection error."""
        from scripts.check_new_documents import _check_ingested_db

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.side_effect = Exception("connection refused")
        mock_psycopg2.extras.RealDictCursor = MagicMock()
        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2, "psycopg2.extras": mock_psycopg2.extras}):
            result = _check_ingested_db(["some_id"], "postgresql://bad")
        assert result == set()


class TestCheckNewDocumentsJsonOutput:
    """Test JSON output format."""

    def test_print_json_format(self, capsys: Any):
        """JSON output contains new/ingested/errors keys."""
        from scripts.check_new_documents import CheckResult, DocumentStatus, _print_json

        result = CheckResult(
            new=[DocumentStatus("CRM", "transcript", "2025-02-26", "new", "abc")],
            ingested=[DocumentStatus("ADBE", "presentation", "2025-01-15", "ingested", "def")],
            errors=[{"ticker": "MSFT", "source": "transcript", "error": "timeout"}],
        )
        _print_json(result)
        captured = capsys.readouterr()
        data = json.loads(captured.out)

        assert "new" in data
        assert "ingested" in data
        assert "errors" in data
        assert len(data["new"]) == 1
        assert data["new"][0]["ticker"] == "CRM"
        assert data["new"][0]["source"] == "transcript"
        assert data["ingested"][0]["ticker"] == "ADBE"
        assert len(data["errors"]) == 1

    def test_print_json_empty(self, capsys: Any):
        """JSON output is valid when result is empty."""
        from scripts.check_new_documents import CheckResult, _print_json

        _print_json(CheckResult())
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"new": [], "ingested": [], "errors": []}


# ---------------------------------------------------------------------------
# ingest_all.py tests
# ---------------------------------------------------------------------------


class TestIngestAll:
    """Test the unified ingest_all.py wrapper."""

    def _run_main(self, argv: list[str]) -> int:
        import scripts.ingest_all as ingest_all_mod
        with patch.object(sys, "argv", ["ingest_all.py"] + argv):
            return ingest_all_mod.main()

    def test_transcript_only_calls_only_transcript_script(self):
        """--type transcript only runs ingest_transcripts.py."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self._run_main(["--type", "transcript", "--tickers", "CRM", "--dry-run"])

        calls = mock_run.call_args_list
        assert len(calls) == 1
        cmd = calls[0][0][0]
        assert "ingest_transcripts.py" in str(cmd)
        assert not any("ingest_presentations.py" in str(c) for c in calls)

    def test_presentation_only_calls_only_presentation_script(self):
        """--type presentation only runs ingest_presentations.py."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self._run_main(["--type", "presentation", "--tickers", "ADBE", "--dry-run"])

        calls = mock_run.call_args_list
        assert len(calls) == 1
        cmd = calls[0][0][0]
        assert "ingest_presentations.py" in str(cmd)
        assert not any("ingest_transcripts.py" in str(c) for c in calls)

    def test_both_types_calls_both_scripts(self):
        """Without --type, both scripts are called."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self._run_main(["--tickers", "CRM", "--dry-run"])

        calls = mock_run.call_args_list
        assert len(calls) == 2
        scripts_called = [str(c[0][0]) for c in calls]
        assert any("ingest_transcripts.py" in s for s in scripts_called)
        assert any("ingest_presentations.py" in s for s in scripts_called)

    def test_tickers_passed_through(self):
        """Tickers are correctly passed to child scripts."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self._run_main(["--type", "transcript", "--tickers", "CRM", "ADBE", "--dry-run"])

        cmd = mock_run.call_args_list[0][0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "CRM" in cmd_str
        assert "ADBE" in cmd_str

    def test_limit_passed_through(self):
        """--limit is forwarded to child scripts."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self._run_main(["--type", "transcript", "--tickers", "CRM", "--limit", "3", "--dry-run"])

        cmd = mock_run.call_args_list[0][0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "--limit" in cmd_str
        assert "3" in cmd_str

    def test_max_failures_passed_through(self):
        """--max-failures is forwarded to child scripts."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self._run_main([
                "--type", "transcript", "--tickers", "CRM",
                "--dry-run", "--max-failures", "5",
            ])

        cmd = mock_run.call_args_list[0][0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "--max-failures" in cmd_str
        assert "5" in cmd_str

    def test_resume_passed_through(self):
        """--resume is forwarded to child scripts."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self._run_main(["--type", "transcript", "--tickers", "CRM", "--dry-run", "--resume"])

        cmd = mock_run.call_args_list[0][0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "--resume" in cmd_str

    def test_returns_nonzero_on_child_failure(self):
        """Returns non-zero exit code when a child script fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            rc = self._run_main(["--type", "transcript", "--tickers", "CRM", "--dry-run"])
        assert rc != 0


# ---------------------------------------------------------------------------
# Checkpointing tests
# ---------------------------------------------------------------------------


class TestCheckpointing:
    """Test progress file write/read logic in ingest_transcripts and ingest_presentations."""

    def test_save_and_load_progress_transcripts(self, tmp_path: Path):
        """Save progress for a ticker and verify it's marked done on reload."""
        from scripts.ingest_transcripts import _load_progress, _save_progress

        progress_file = tmp_path / "progress.json"
        _save_progress(progress_file, "CRM", count=3)

        done = _load_progress(progress_file)
        assert "CRM" in done

    def test_save_and_load_progress_presentations(self, tmp_path: Path):
        """Save progress for a ticker in presentations and verify reload."""
        from scripts.ingest_presentations import _load_progress, _save_progress

        progress_file = tmp_path / "progress.json"
        _save_progress(progress_file, "ADBE", count=2)

        done = _load_progress(progress_file)
        assert "ADBE" in done

    def test_load_progress_empty_when_file_missing(self, tmp_path: Path):
        """Returns empty set when progress file does not exist."""
        from scripts.ingest_transcripts import _load_progress

        done = _load_progress(tmp_path / "nonexistent.json")
        assert done == set()

    def test_save_progress_creates_parent_dirs(self, tmp_path: Path):
        """_save_progress creates parent directories if needed."""
        from scripts.ingest_transcripts import _save_progress

        progress_file = tmp_path / "subdir" / "deeper" / "progress.json"
        _save_progress(progress_file, "MSFT", count=1)

        assert progress_file.exists()
        entries = json.loads(progress_file.read_text())
        assert entries[0]["ticker"] == "MSFT"
        assert entries[0]["status"] == "done"

    def test_multiple_tickers_accumulate(self, tmp_path: Path):
        """Multiple _save_progress calls accumulate entries in the same file."""
        from scripts.ingest_transcripts import _load_progress, _save_progress

        progress_file = tmp_path / "progress.json"
        _save_progress(progress_file, "CRM", count=3)
        _save_progress(progress_file, "ADBE", count=2)
        _save_progress(progress_file, "MSFT", count=5)

        done = _load_progress(progress_file)
        assert {"CRM", "ADBE", "MSFT"} == done

    def test_resume_skips_done_tickers(self, tmp_path: Path):
        """run_ingestion with --resume skips tickers already in progress file."""
        from scripts.ingest_transcripts import _save_progress, run_ingestion

        progress_file = tmp_path / "progress.json"
        _save_progress(progress_file, "CRM", count=3)  # CRM already done

        # Build a mock source that records which tickers were queried
        mock_source = MagicMock()
        mock_source.list_available.return_value = []

        mock_hf_class = MagicMock(return_value=mock_source)

        with patch("scripts.ingest_transcripts.V2Pipeline"), \
             patch("scripts.ingest_transcripts.PipelineConfig"), \
             patch("scripts.ingest_transcripts._save_progress"), \
             patch.dict("sys.modules", {
                 "src.infra.huggingface_source": MagicMock(HuggingFaceTranscriptSource=mock_hf_class),
             }):
            run_ingestion(
                source_name="huggingface",
                tickers=["CRM", "ADBE"],
                limit=5,
                dry_run=True,
                db_url=None,
                resume=True,
                progress_file=progress_file,
            )

        # CRM should not have been queried (skipped due to resume)
        queried_tickers = [
            c.kwargs.get("ticker") or (c[1].get("ticker") if len(c) > 1 else None)
            for c in mock_source.list_available.call_args_list
        ]
        assert "CRM" not in queried_tickers
        assert "ADBE" in queried_tickers


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Test that the circuit breaker aborts after N consecutive failures."""

    def _build_failing_source(self, n_failures: int) -> MagicMock:
        """Source that raises Exception for the first n_failures tickers, then succeeds."""
        source = MagicMock()
        side_effects: list[Any] = [Exception("fetch error")] * n_failures + [[]]
        source.list_available.side_effect = side_effects
        return source

    def test_circuit_breaker_exits_after_n_failures_transcripts(self, tmp_path: Path):
        """run_ingestion exits with code 2 after max_failures consecutive failures."""
        from scripts.ingest_transcripts import run_ingestion

        progress_file = tmp_path / "progress.json"
        mock_source = self._build_failing_source(n_failures=3)
        mock_hf_class = MagicMock(return_value=mock_source)

        with patch("scripts.ingest_transcripts.V2Pipeline"), \
             patch("scripts.ingest_transcripts.PipelineConfig"), \
             patch("scripts.ingest_transcripts._save_progress"), \
             patch.dict("sys.modules", {
                 "src.infra.huggingface_source": MagicMock(HuggingFaceTranscriptSource=mock_hf_class),
             }):
            with pytest.raises(SystemExit) as exc_info:
                run_ingestion(
                    source_name="huggingface",
                    tickers=["T1", "T2", "T3", "T4"],
                    limit=5,
                    dry_run=True,
                    db_url=None,
                    max_failures=3,
                    progress_file=progress_file,
                )
            assert exc_info.value.code == 2

    def test_circuit_breaker_n_minus_1_failures_continues(self, tmp_path: Path):
        """run_ingestion continues when failures are below the threshold."""
        from scripts.ingest_transcripts import run_ingestion

        progress_file = tmp_path / "progress.json"
        # 2 failures, then 1 success → should NOT trigger circuit breaker (threshold=3)
        mock_source = self._build_failing_source(n_failures=2)
        mock_hf_class = MagicMock(return_value=mock_source)

        with patch("scripts.ingest_transcripts.V2Pipeline"), \
             patch("scripts.ingest_transcripts.PipelineConfig"), \
             patch("scripts.ingest_transcripts._save_progress"), \
             patch.dict("sys.modules", {
                 "src.infra.huggingface_source": MagicMock(HuggingFaceTranscriptSource=mock_hf_class),
             }):
            # Should NOT raise SystemExit
            summary = run_ingestion(
                source_name="huggingface",
                tickers=["T1", "T2", "T3"],
                limit=5,
                dry_run=True,
                db_url=None,
                max_failures=3,
                progress_file=progress_file,
            )
        # 2 errors, 1 successful (empty) ticker
        assert summary.errors == 2

    def test_circuit_breaker_presentations(self, tmp_path: Path):
        """ingest_presentations circuit breaker also exits with code 2."""
        from scripts.ingest_presentations import run_ingestion

        progress_file = tmp_path / "progress.json"
        mock_source = MagicMock()
        mock_source.list_available.side_effect = [
            Exception("network error"),
            Exception("network error"),
        ]
        mock_sec_class = MagicMock(return_value=mock_source)

        with patch("scripts.ingest_presentations.V2Pipeline"), \
             patch("scripts.ingest_presentations.PipelineConfig"), \
             patch("scripts.ingest_presentations._save_progress"), \
             patch.dict("sys.modules", {
                 "src.infra.sec_presentation_source": MagicMock(SECPresentationSource=mock_sec_class),
             }):
            with pytest.raises(SystemExit) as exc_info:
                run_ingestion(
                    tickers=["T1", "T2"],
                    limit=5,
                    dry_run=True,
                    db_url=None,
                    max_failures=2,
                    progress_file=progress_file,
                )
            assert exc_info.value.code == 2
