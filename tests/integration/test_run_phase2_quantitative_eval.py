"""Integration test for ``scripts/run_phase2_quantitative_eval.py``.

Covers:
  - ``--dry-run --gold-only`` end-to-end: corpus selection from real
    split_v1.json, label construction, CSV header written, summary skeleton
    with go_no_go='DRY_RUN', exits 0 without API calls.

The Anthropic API and V2 pipeline are never invoked; the ``clean_db`` fixture
is used for structural parity (the script queries the DB only when not dry-run
and not gold-only).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_phase2_quantitative_eval.py"


def _load_script_module() -> object:
    """Load the Phase-2 script via importlib (isolated module namespace)."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "run_phase2_quantitative_eval_integration"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


# ---------------------------------------------------------------------------
# --dry-run --gold-only end-to-end
# ---------------------------------------------------------------------------


def test_dry_run_gold_only_exits_0_and_writes_files(cli, clean_db, tmp_path, monkeypatch):
    """--dry-run --gold-only: corpus selection + CSV header + summary, exit 0.

    ``clean_db`` is provided for fixture parity; the dry-run path does not
    query the DB because DATABASE_URL is cleared and --gold-only skips the
    reviewed corpus.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    exit_code, summary = cli.run_eval(
        run_id="integ_dryrun",
        out_dir=tmp_path,
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=True,
        resume=False,
        i_accept_cost=False,
    )

    assert exit_code == 0, f"Expected exit 0, got {exit_code}: {summary}"

    csv_path = tmp_path / "phase2_quantitative_integ_dryrun.csv"
    summary_path = tmp_path / "phase2_quantitative_integ_dryrun_summary.json"
    assert csv_path.exists(), "CSV file not written"
    assert summary_path.exists(), "Summary JSON not written"

    # CSV: header present, no data rows (dry-run writes no API output).
    csv_text = csv_path.read_text()
    header_fields = csv_text.strip().split("\n")[0].split(",")
    assert "run_id" in header_fields
    assert "corpus" in header_fields
    assert "metric_id" in header_fields
    assert "go_no_go" not in header_fields  # go_no_go is in summary, not CSV rows
    # Only the header line.
    assert csv_text.count("\n") == 1, "Dry-run CSV must have only the header line"

    # Summary: structure check.
    loaded = json.loads(summary_path.read_text())
    assert loaded["run_id"] == "integ_dryrun"
    assert loaded["dry_run"] is True
    assert loaded["go_no_go"] == "DRY_RUN"
    assert loaded["gold_only"] is True
    assert isinstance(loaded["selected_gold_filings"], list)
    assert len(loaded["selected_gold_filings"]) >= 1, "At least one gold filing expected"
    assert loaded["selected_reviewed_filings"] == [], "No reviewed filings in --gold-only"
    assert loaded["per_metric"]["gold"] == {}
    assert loaded["per_metric"]["reviewed"] == {}
    assert loaded["per_metric"]["merged"] == {}
    assert isinstance(loaded["metric_ids"], list)
    assert len(loaded["metric_ids"]) > 0, "Enrolled metrics must be non-empty"
    assert loaded["criteria"] == []
    assert loaded["errors"] == []


def test_dry_run_gold_only_is_idempotent(cli, clean_db, tmp_path, monkeypatch):
    """Running dry-run twice with different run-IDs writes separate files."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    for run_id in ["idempotent_a", "idempotent_b"]:
        exit_code, summary = cli.run_eval(
            run_id=run_id,
            out_dir=tmp_path,
            min_reviewed=30,
            cost_budget_usd=25.0,
            limit=None,
            gold_only=True,
            dry_run=True,
            resume=False,
            i_accept_cost=False,
        )
        assert exit_code == 0

    csv_a = tmp_path / "phase2_quantitative_idempotent_a.csv"
    csv_b = tmp_path / "phase2_quantitative_idempotent_b.csv"
    assert csv_a.exists()
    assert csv_b.exists()


def test_dry_run_collision_guard(cli, clean_db, tmp_path, monkeypatch):
    """A second live call with the same run_id exits 2 (output collision guard)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # First dry-run creates the files.
    exit_code, _ = cli.run_eval(
        run_id="collision_guard",
        out_dir=tmp_path,
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=True,
        resume=False,
        i_accept_cost=False,
    )
    assert exit_code == 0

    # Second call (non-dry-run, same run_id) hits the collision guard.
    exit_code2, summary2 = cli.run_eval(
        run_id="collision_guard",
        out_dir=tmp_path,
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=False,
        resume=False,
        i_accept_cost=False,
    )
    assert exit_code2 == 2
    assert "already exists" in summary2.get("error", "").lower()


def test_dry_run_selects_deterministic_gold_corpus(cli, clean_db, tmp_path, monkeypatch):
    """Two dry-runs with the same inputs select identical gold filings."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    _, summary_a = cli.run_eval(
        run_id="determ_a",
        out_dir=tmp_path / "a",
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=True,
        resume=False,
        i_accept_cost=False,
    )
    _, summary_b = cli.run_eval(
        run_id="determ_b",
        out_dir=tmp_path / "b",
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=True,
        resume=False,
        i_accept_cost=False,
    )
    assert sorted(summary_a["selected_gold_filings"]) == sorted(summary_b["selected_gold_filings"])
