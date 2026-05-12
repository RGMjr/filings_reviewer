"""Integration test for scripts/simulate_text_pattern_changes.py.

Covers the DB-touching orchestration path:
  - accepted-rec fetch from text_pattern_recommendation_decisions
  - supported / unsupported rule-type partitioning
  - persistence of text_pattern_simulation_runs + _deltas

V2GoldStandardValidator is too slow + external-resource-heavy for an
integration test, so `_run_validation` and `_get_metrics` are monkey-
patched to return deterministic stub AggregateMetrics. The test
verifies orchestration + persistence shape, not validator behavior.

The script is loaded via importlib (sibling pattern, see
test_analyze_text_decision_patterns.py).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "simulate_text_pattern_changes.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "simulate_text_pattern_changes_integration"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stub_aggregate_metrics(
    *,
    tier1_presence_recall: float = 0.85,
    tier2_presence_recall: float = 0.62,
    presence_by_metric: dict | None = None,
):
    """Build a stub AggregateMetrics-like object good enough for the script."""
    metrics = MagicMock()
    metrics.tier1_presence_recall = tier1_presence_recall
    metrics.tier2_presence_recall = tier2_presence_recall
    metrics.presence_by_metric = presence_by_metric or {}
    return metrics


def _seed_accepted_rec(
    db,
    *,
    metric_id: str,
    rule: str,
    decision_key: str,
    reviewer_id: str = "test-reviewer",
) -> str:
    """Insert an 'accepted' rec into text_pattern_recommendation_decisions.

    Returns the inserted row id.
    """
    rows = db.query(
        """
        INSERT INTO text_pattern_recommendation_decisions
            (metric_id, rule, decision_key, decision, reviewer_id)
        VALUES
            (%(metric_id)s, %(rule)s, %(decision_key)s, 'accepted', %(reviewer_id)s)
        RETURNING id
        """,
        {
            "metric_id": metric_id,
            "rule": rule,
            "decision_key": decision_key,
            "reviewer_id": reviewer_id,
        },
    )
    return str(rows[0]["id"])


def _make_args(database_url: str, run_id: str | None = None) -> Namespace:
    return Namespace(
        database_url=database_url,
        run_id=run_id,
        triggered_by="test",
        max_companies=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_one_accepted_exclusion_rec(cli, clean_db, monkeypatch, test_db_url):
    """Seed one accepted exclusion_pattern rec, run script, assert persistence."""
    metric_id = "cm_active_customers_total"
    _seed_accepted_rec(
        clean_db,
        metric_id=metric_id,
        rule="exclusion_pattern",
        decision_key="accounts receivable",
    )

    # Pre-insert a 'running' row so the script picks up our run_id and
    # only does the UPDATE-to-succeeded path (mirrors the web-trigger path).
    run_id = str(uuid.uuid4())
    clean_db.execute(
        """
        INSERT INTO text_pattern_simulation_runs (id, status, triggered_by)
        VALUES (%(id)s, 'running', 'test')
        """,
        {"id": run_id},
    )

    # Stub the validator paths. Return deterministic AggregateMetrics with
    # a presence_by_metric entry for the affected metric.
    stub_baseline = _make_stub_aggregate_metrics(
        presence_by_metric={
            metric_id: MagicMock(precision=0.9, recall=0.8, f1=0.85),
        },
    )
    stub_patched = _make_stub_aggregate_metrics(
        tier1_presence_recall=0.85,  # equal — no regression
        presence_by_metric={
            metric_id: MagicMock(precision=0.95, recall=0.8, f1=0.87),
        },
    )

    def _stub_run_validation(override, companies):
        return MagicMock()  # validator object; _get_metrics resolves it

    call_count = {"n": 0}

    def _stub_get_metrics(validator):
        call_count["n"] += 1
        # First call = baseline; subsequent calls = patched (both retry runs).
        return stub_baseline if call_count["n"] == 1 else stub_patched

    monkeypatch.setattr(cli, "_run_validation", _stub_run_validation)
    monkeypatch.setattr(cli, "_get_metrics", _stub_get_metrics)
    # Skip the gold-standard CSV loader; just claim every metric is covered.
    monkeypatch.setattr(
        cli,
        "_load_affected_companies",
        lambda metric_ids, max_companies: ["Stub Company"],
    )
    monkeypatch.setattr(
        cli,
        "_compute_coverage",
        lambda metric_ids: {m: {"coverage_filings": 5, "coverage_facts": 12} for m in metric_ids},
    )

    args = _make_args(test_db_url, run_id=run_id)
    cli._orchestrate(args)

    # Assert run row succeeded
    run_rows = clean_db.query(
        "SELECT status, num_recs_simulated, num_companies_validated, "
        "tier1_presence_recall_baseline, tier1_presence_recall_patched, "
        "tier1_regressed, runs_agree "
        "FROM text_pattern_simulation_runs WHERE id = %(id)s",
        {"id": run_id},
    )
    assert len(run_rows) == 1
    row = dict(run_rows[0])
    assert row["status"] == "succeeded"
    assert row["num_recs_simulated"] == 1
    assert row["num_companies_validated"] == 1
    assert float(row["tier1_presence_recall_baseline"]) == pytest.approx(0.85)
    assert float(row["tier1_presence_recall_patched"]) == pytest.approx(0.85)
    assert row["tier1_regressed"] is False
    assert row["runs_agree"] is True

    # Assert at least one delta row exists for the affected metric
    deltas = clean_db.query(
        "SELECT metric_id, baseline_recall, patched_recall, coverage_filings "
        "FROM text_pattern_simulation_deltas WHERE run_id = %(id)s",
        {"id": run_id},
    )
    assert len(deltas) >= 1
    metric_ids = {d["metric_id"] for d in deltas}
    assert metric_id in metric_ids
    delta = next(d for d in deltas if d["metric_id"] == metric_id)
    assert float(delta["baseline_recall"]) == pytest.approx(0.8)
    assert float(delta["patched_recall"]) == pytest.approx(0.8)
    assert delta["coverage_filings"] == 5


def test_no_accepted_recs_still_succeeds(cli, clean_db, monkeypatch, test_db_url):
    """Zero accepted recs is a valid (no-op) run — script should still succeed.

    The endpoint blocks this case with 409 'no_accepted_recs', but the script
    itself shouldn't fail.
    """
    run_id = str(uuid.uuid4())
    clean_db.execute(
        """
        INSERT INTO text_pattern_simulation_runs (id, status, triggered_by)
        VALUES (%(id)s, 'running', 'test')
        """,
        {"id": run_id},
    )

    stub_metrics = _make_stub_aggregate_metrics()
    monkeypatch.setattr(cli, "_run_validation", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cli, "_get_metrics", lambda v: stub_metrics)
    monkeypatch.setattr(cli, "_load_affected_companies", lambda metric_ids, max_companies: [])
    monkeypatch.setattr(cli, "_compute_coverage", lambda metric_ids: {})

    args = _make_args(test_db_url, run_id=run_id)
    cli._orchestrate(args)

    run_rows = clean_db.query(
        "SELECT status, num_recs_simulated FROM text_pattern_simulation_runs WHERE id = %(id)s",
        {"id": run_id},
    )
    assert len(run_rows) == 1
    assert run_rows[0]["status"] == "succeeded"
    assert run_rows[0]["num_recs_simulated"] == 0


def test_unsupported_rule_type_silently_skipped(cli, clean_db, monkeypatch, test_db_url):
    """keyword_overlap recs are skipped; num_recs_simulated reflects supported only."""
    _seed_accepted_rec(
        clean_db,
        metric_id="cm_active_customers_total",
        rule="keyword_overlap",
        decision_key="cm_some_other_metric",
    )

    run_id = str(uuid.uuid4())
    clean_db.execute(
        """
        INSERT INTO text_pattern_simulation_runs (id, status, triggered_by)
        VALUES (%(id)s, 'running', 'test')
        """,
        {"id": run_id},
    )

    stub_metrics = _make_stub_aggregate_metrics()
    monkeypatch.setattr(cli, "_run_validation", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cli, "_get_metrics", lambda v: stub_metrics)
    monkeypatch.setattr(cli, "_load_affected_companies", lambda metric_ids, max_companies: [])
    monkeypatch.setattr(cli, "_compute_coverage", lambda metric_ids: {})

    args = _make_args(test_db_url, run_id=run_id)
    cli._orchestrate(args)

    run_rows = clean_db.query(
        "SELECT status, num_recs_simulated FROM text_pattern_simulation_runs WHERE id = %(id)s",
        {"id": run_id},
    )
    assert run_rows[0]["status"] == "succeeded"
    assert run_rows[0]["num_recs_simulated"] == 0

    # No deltas for the unsupported rec
    delta_count = clean_db.query(
        "SELECT COUNT(*) AS n FROM text_pattern_simulation_deltas WHERE run_id = %(id)s",
        {"id": run_id},
    )
    assert delta_count[0]["n"] == 0
