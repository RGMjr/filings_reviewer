"""Integration tests for the Ship-to-PR machinery (Track D).

Covers:
  - scripts/open_pattern_recommendation_pr.py happy path: seed accepted recs +
    a succeeded sim run + a queued ship row, monkeypatch git/gh subprocess
    calls, assert YAML edit + DB writeback.
  - POST /api/v2/extraction/ship-to-pr sim-gate denial (tier1_regressed=True).
  - POST /api/v2/extraction/ship-to-pr stale-row sweep (>1h running row).

The script is loaded via importlib (sibling pattern, see
tests/integration/test_simulate_text_pattern_changes.py).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import uuid
from argparse import Namespace
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "open_pattern_recommendation_pr.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "open_pattern_recommendation_pr_integration"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


@pytest.fixture(autouse=True)
def _isolate_ship_tables(clean_db):
    """Truncate ship/sim/rec tables before each test — `clean_db` doesn't.

    Sibling tests in the xdist worker (e.g. test_simulate_text_pattern_changes)
    leave rows in these tables that pollute the gate checks.
    """
    clean_db.execute("TRUNCATE TABLE text_pattern_ship_runs CASCADE")
    clean_db.execute("TRUNCATE TABLE text_pattern_simulation_deltas CASCADE")
    clean_db.execute("TRUNCATE TABLE text_pattern_simulation_runs CASCADE")
    clean_db.execute("TRUNCATE TABLE text_pattern_recommendation_decisions CASCADE")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_accepted_rec(
    db,
    *,
    metric_id: str,
    decision_key: str,
    reviewer_id: str = "RGM",
) -> str:
    rows = db.query(
        """
        INSERT INTO text_pattern_recommendation_decisions
            (metric_id, rule, decision_key, decision, reviewer_id)
        VALUES
            (%(metric_id)s, 'exclusion_pattern', %(decision_key)s, 'accepted', %(reviewer_id)s)
        RETURNING id
        """,
        {
            "metric_id": metric_id,
            "decision_key": decision_key,
            "reviewer_id": reviewer_id,
        },
    )
    return str(rows[0]["id"])


def _seed_sim_run(
    db,
    *,
    rec_ids: list[str],
    metric_ids: list[str],
    tier1_regressed: bool = False,
    runs_agree: bool = True,
    coverage_filings: int = 5,
) -> str:
    sim_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO text_pattern_simulation_runs
            (id, status, started_at, completed_at,
             tier1_presence_recall_baseline, tier1_presence_recall_patched,
             tier1_regressed, runs_agree, triggered_by)
        VALUES
            (%(id)s, 'succeeded', NOW(), NOW(),
             0.85, 0.85, %(t1r)s, %(agree)s, 'test')
        """,
        {"id": sim_id, "t1r": tier1_regressed, "agree": runs_agree},
    )
    # Stamp one delta per rec so the covering-simulation SQL passes.
    for rec_id, metric_id in zip(rec_ids, metric_ids, strict=True):
        db.execute(
            """
            INSERT INTO text_pattern_simulation_deltas
                (run_id, recommendation_decision_id, metric_id,
                 baseline_recall, patched_recall, coverage_filings)
            VALUES (%(run)s, %(rec)s, %(metric)s, 0.8, 0.82, %(cf)s)
            """,
            {
                "run": sim_id,
                "rec": rec_id,
                "metric": metric_id,
                "cf": coverage_filings,
            },
        )
    return sim_id


def _seed_ship_run(
    db,
    *,
    rec_ids: list[str],
    sim_id: str,
    status: str = "running",
) -> str:
    run_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO text_pattern_ship_runs
            (id, status, recommendation_decision_ids, simulation_run_id, triggered_by)
        VALUES
            (%(id)s, %(status)s, %(rec_ids)s::jsonb, %(sim_id)s, 'RGM')
        """,
        {
            "id": run_id,
            "status": status,
            "rec_ids": json.dumps(rec_ids),
            "sim_id": sim_id,
        },
    )
    return run_id


# ---------------------------------------------------------------------------
# Test 1: Script happy path
# ---------------------------------------------------------------------------


def test_script_happy_path_edits_yaml_and_writes_pr_back(
    cli, clean_db, monkeypatch, test_db_url, tmp_path
):
    """Seed accepted rec + sim + queued ship row → assert end-to-end write.

    YAML editing is verified against a tmp_path copy of the real
    config/metric_keywords.yaml so the test doesn't mutate the working tree.
    git + gh subprocess calls are monkeypatched.
    """
    metric_id = "cm_active_customers_total"
    phrase = "accounts receivable test phrase"

    rec_id = _seed_accepted_rec(clean_db, metric_id=metric_id, decision_key=phrase)
    sim_id = _seed_sim_run(clean_db, rec_ids=[rec_id], metric_ids=[metric_id])
    run_id = _seed_ship_run(clean_db, rec_ids=[rec_id], sim_id=sim_id, status="running")

    # Stage a writable YAML copy so the test edits a tmp file, not the real one.
    real_yaml = PROJECT_ROOT / "config" / "metric_keywords.yaml"
    tmp_yaml = tmp_path / "metric_keywords.yaml"
    shutil.copy(real_yaml, tmp_yaml)
    monkeypatch.setattr(cli, "YAML_PATH", tmp_yaml)

    # Capture the git/gh shell-outs so the test doesn't actually push anything.
    captured_runs: list[list[str]] = []

    def _stub_run(cmd, cwd, *, capture=False):
        captured_runs.append(cmd)
        if capture and cmd[:3] == ["gh", "pr", "create"]:
            return "https://github.com/anthropics/test/pull/9999\n"
        return ""

    monkeypatch.setattr(cli, "_run", _stub_run)

    cli._orchestrate(Namespace(database_url=test_db_url, run_id=run_id))

    # Assert YAML now contains the appended phrase.
    yaml_text = tmp_yaml.read_text(encoding="utf-8")
    assert phrase in yaml_text, "YAML edit did not land"

    # Assert git/gh shell-outs fired in the expected order.
    cmd_heads = [c[:2] for c in captured_runs]
    assert ["git", "checkout"] in cmd_heads
    assert ["git", "add"] in cmd_heads
    assert ["git", "commit"] in cmd_heads
    assert ["git", "push"] in cmd_heads
    assert ["gh", "pr"] in cmd_heads

    commit_cmd = next(c for c in captured_runs if c[:2] == ["git", "commit"])
    assert "--no-verify" in commit_cmd, "commit must skip local hooks"

    # Assert DB writeback: rec rows + ship row.
    rec_rows = clean_db.query(
        "SELECT pr_number, pr_url FROM text_pattern_recommendation_decisions WHERE id=%(id)s",
        {"id": rec_id},
    )
    assert rec_rows[0]["pr_number"] == 9999
    assert rec_rows[0]["pr_url"].endswith("/pull/9999")

    ship_rows = clean_db.query(
        "SELECT status, pr_number, pr_url, branch_name, completed_at "
        "FROM text_pattern_ship_runs WHERE id=%(id)s",
        {"id": run_id},
    )
    ship = dict(ship_rows[0])
    assert ship["status"] == "succeeded"
    assert ship["pr_number"] == 9999
    assert ship["branch_name"].startswith("ship/pattern-recs-")
    assert ship["completed_at"] is not None


# ---------------------------------------------------------------------------
# Test 2: Endpoint sim-gate denial (tier1_regressed=True)
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch, test_db_adapter):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("DATABASE_URL", test_db_adapter.connection_string)
    monkeypatch.setenv("FILINGS_API_KEY", "test-key")

    from src.web.app import create_app

    flask_app = create_app("testing")
    flask_app.config["DATABASE_URL"] = test_db_adapter.connection_string
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def _auth_headers():
    """Headers that satisfy `@require(INGEST_RUN)` on the endpoint."""
    return {"X-API-Key": "test-key"}


def test_endpoint_rejects_when_tier1_regressed(client, clean_db, _auth_headers):
    metric_id = "cm_active_customers_total"
    rec_id = _seed_accepted_rec(clean_db, metric_id=metric_id, decision_key="phrase A")
    sim_id = _seed_sim_run(
        clean_db,
        rec_ids=[rec_id],
        metric_ids=[metric_id],
        tier1_regressed=True,
    )

    resp = client.post(
        "/api/v2/extraction/ship-to-pr",
        headers=_auth_headers,
        json={"reviewer_id": "RGM"},
    )
    assert resp.status_code == 409, resp.get_json()
    body = resp.get_json()
    assert body["error"] == "tier1_regressed"
    assert body["simulation_run_id"] == sim_id

    # No ship run was enqueued.
    ship_count = clean_db.query("SELECT COUNT(*) AS n FROM text_pattern_ship_runs")
    assert ship_count[0]["n"] == 0


# ---------------------------------------------------------------------------
# Test 3: Endpoint stale-row sweep
# ---------------------------------------------------------------------------


def test_endpoint_sweeps_stale_running_row(client, clean_db, _auth_headers):
    """A running row >1h old should be auto-flipped to failed on entry."""
    metric_id = "cm_active_customers_total"
    rec_id = _seed_accepted_rec(clean_db, metric_id=metric_id, decision_key="phrase B")
    sim_id = _seed_sim_run(clean_db, rec_ids=[rec_id], metric_ids=[metric_id])

    stale_run_id = str(uuid.uuid4())
    clean_db.execute(
        """
        INSERT INTO text_pattern_ship_runs
            (id, status, started_at, recommendation_decision_ids, simulation_run_id, triggered_by)
        VALUES
            (%(id)s, 'running', NOW() - INTERVAL '2 hours',
             %(rec_ids)s::jsonb, %(sim_id)s, 'RGM')
        """,
        {
            "id": stale_run_id,
            "rec_ids": json.dumps([rec_id]),
            "sim_id": sim_id,
        },
    )

    resp = client.post(
        "/api/v2/extraction/ship-to-pr",
        headers=_auth_headers,
        json={"reviewer_id": "RGM"},
    )
    # After sweep the stale row is failed → no running rows → endpoint enqueues
    # a fresh queued row and returns 202.
    assert resp.status_code == 202, resp.get_json()

    # Original stale row was flipped to failed.
    swept = clean_db.query(
        "SELECT status, error FROM text_pattern_ship_runs WHERE id=%(id)s",
        {"id": stale_run_id},
    )
    assert swept[0]["status"] == "failed"
    assert "stale" in (swept[0]["error"] or "")

    # New queued row exists.
    queued = clean_db.query(
        "SELECT id, status FROM text_pattern_ship_runs WHERE id <> %(id)s",
        {"id": stale_run_id},
    )
    assert len(queued) == 1
    assert queued[0]["status"] == "queued"
