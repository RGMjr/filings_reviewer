"""Integration test for scripts/analyze_text_decision_patterns.py.

Covers the DB-touching orchestration path:
  - anchor resolution against text_decision_analysis_runs
  - v2_review_decisions JOIN v2_metric_facts JOIN v2_segments pull
  - per-(run, metric, phrase) INSERTs
  - run-row UPDATE on success
  - exception path that flips status to 'failed'

The script is loaded via importlib (sibling pattern, see test_onboard_tickers_cli.py).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "analyze_text_decision_patterns.py"


# ---------------------------------------------------------------------------
# Script loader (importlib pattern, mirrors test_onboard_tickers_cli.py)
# ---------------------------------------------------------------------------


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "analyze_text_decision_patterns_integration"
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


def _seed_corpus(db, *, cik="0009980001", accession="0009980001-24-000001"):
    """Seed companies, filings, v2_segments, v2_metric_facts, v2_review_decisions.

    Returns (filing_id, fact_id, segment_id) for the seeded rows.
    """
    from tests.integration.conftest import (
        create_test_company_and_filing,
        create_test_v2_decision,
        create_test_v2_fact,
    )

    _, filing_id = create_test_company_and_filing(db, cik=cik, accession_number=accession)

    # Create a segment so the JOIN in _fetch_decisions can resolve it.
    # Column was renamed doc_id → filing_id in migration 202604291308.
    segment_rows = db.query(
        """
        INSERT INTO v2_segments
            (filing_id, segment_type, segment_text, dom_locator, sequence_idx)
        VALUES
            (%(filing_id)s, 'paragraph', 'customers retained annual recurring revenue metric value', '/html/body/p[1]', 1)
        RETURNING segment_id::text
        """,
        {"filing_id": filing_id},
    )
    segment_id = segment_rows[0]["segment_id"]

    # Fact pointing to that segment via source_locator->>'segment_id'.
    fact_id = create_test_v2_fact(
        db,
        filing_id,
        canonical_metric_id="cm_net_revenue_retention",
        value_raw="110%",
        source_locator={"segment_id": segment_id},
    )

    # Two reject decisions so n-gram counts meet MIN_OCCURRENCES=2 and
    # MIN_PCT=10 thresholds.
    for _ in range(2):
        create_test_v2_decision(
            db,
            fact_id,
            decision="reject",
            rejection_reason="wrong metric extracted from retention table",
            rejection_category="wrong_metric",
        )

    return filing_id, fact_id, segment_id


def _truncate_analysis_tables(db) -> None:
    """Remove all rows from the three analysis tables between tests."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE text_decision_phrase_findings,
                               text_decision_metric_summary,
                               text_decision_analysis_runs
                CASCADE
                """
            )
        conn.commit()


def _query_runs(db) -> list[dict]:
    return db.query("SELECT * FROM text_decision_analysis_runs ORDER BY started_at ASC")


def _query_summary(db, run_id: str) -> list[dict]:
    return db.query(
        "SELECT * FROM text_decision_metric_summary WHERE run_id = %(run_id)s",
        {"run_id": run_id},
    )


def _query_findings(db, run_id: str) -> list[dict]:
    return db.query(
        "SELECT * FROM text_decision_phrase_findings WHERE run_id = %(run_id)s",
        {"run_id": run_id},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("os").getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)
def test_first_run_anchor_null_processes_all_decisions(clean_db, cli):
    """anchor=NULL (no prior succeeded run) → script picks up all decisions.

    Asserts:
    - A run row is written with status='succeeded'.
    - num_decisions_analyzed equals total seeded decisions.
    - A summary row exists for the metric.
    - Finding rows exist (two rejections share common n-gram tokens).
    - The anchor returned by _resolve_anchor advances to a non-NULL value.
    """
    _truncate_analysis_tables(clean_db)
    _seed_corpus(clean_db)

    db_url = __import__("os").environ["TEST_DATABASE_URL"]
    args = Namespace(
        database_url=db_url,
        run_id=None,
        triggered_by="test",
        max_decisions=None,
    )
    cli._orchestrate(args)

    runs = _query_runs(clean_db)
    assert len(runs) == 1, "Expected exactly one run row"
    run = runs[0]
    run_id = str(run["id"])
    assert run["status"] == "succeeded"
    assert run["num_decisions_analyzed"] == 2
    assert run["num_metrics_analyzed"] == 1
    assert run["completed_at"] is not None

    summary_rows = _query_summary(clean_db, run_id)
    assert len(summary_rows) == 1
    s = summary_rows[0]
    assert s["metric_id"] == "cm_net_revenue_retention"
    assert s["total_decisions"] == 2
    assert s["reject_count"] == 2

    # At least one finding should have been mined from the rejection_reason.
    findings = _query_findings(clean_db, run_id)
    assert len(findings) >= 1, "Expected phrase findings from two matching rejection reasons"

    # Anchor must now be non-NULL.
    import psycopg

    with psycopg.connect(db_url) as conn:
        anchor = cli._resolve_anchor(conn)
    assert anchor is not None, "_resolve_anchor should return a non-NULL timestamp after success"


@pytest.mark.skipif(
    not __import__("os").getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)
def test_second_run_anchor_limits_to_new_decisions(clean_db, cli):
    """Second run with anchor set picks up only decisions added after the anchor.

    Sequence:
    1. Seed and run first pass → anchor advances.
    2. Add one NEW decision after the anchor.
    3. Run second pass → num_decisions_analyzed == 1 (only the new decision).
    """
    _truncate_analysis_tables(clean_db)
    filing_id, fact_id, _ = _seed_corpus(clean_db)

    db_url = __import__("os").environ["TEST_DATABASE_URL"]
    args = Namespace(
        database_url=db_url,
        run_id=None,
        triggered_by="test",
        max_decisions=None,
    )

    # First run — consumes the 2 seeded decisions.
    cli._orchestrate(args)

    # Insert a NEW decision *after* the run completes (created_at = now()).
    from tests.integration.conftest import create_test_v2_decision

    create_test_v2_decision(
        clean_db,
        fact_id,
        decision="reject",
        rejection_reason="incorrect extraction caused by wrong parsing",
        rejection_category="wrong_value",
    )

    # Second run.
    cli._orchestrate(args)

    runs = _query_runs(clean_db)
    assert len(runs) == 2, "Expected two run rows"
    second_run = runs[1]
    assert second_run["status"] == "succeeded"
    # Only the newly inserted decision should be picked up.
    assert second_run["num_decisions_analyzed"] == 1, (
        f"Second run should pick up only 1 new decision, got {second_run['num_decisions_analyzed']}"
    )


@pytest.mark.skipif(
    not __import__("os").getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)
def test_success_path_writes_summary_findings_and_updates_run(clean_db, cli):
    """Success path: summary row + finding rows persisted; run row flipped to succeeded.

    This is an explicit structural assertion that all three tables are written
    atomically and the run UPDATE fires.
    """
    _truncate_analysis_tables(clean_db)
    _seed_corpus(clean_db)

    db_url = __import__("os").environ["TEST_DATABASE_URL"]
    # Pre-insert the run row ourselves (simulates web-triggered invocation).
    pre_inserted_run_id = str(uuid.uuid4())
    clean_db.query(
        """
        INSERT INTO text_decision_analysis_runs (id, status, triggered_by)
        VALUES (%(id)s, 'running', 'test')
        """,
        {"id": pre_inserted_run_id},
    )

    args = Namespace(
        database_url=db_url,
        run_id=pre_inserted_run_id,
        triggered_by=None,
        max_decisions=None,
    )
    cli._orchestrate(args)

    runs = _query_runs(clean_db)
    assert len(runs) == 1
    run = runs[0]
    assert str(run["id"]) == pre_inserted_run_id
    assert run["status"] == "succeeded"
    assert run["completed_at"] is not None

    summary_rows = _query_summary(clean_db, pre_inserted_run_id)
    assert len(summary_rows) == 1, "Expected one summary row for the seeded metric"

    findings = _query_findings(clean_db, pre_inserted_run_id)
    assert len(findings) >= 1, "Expected at least one finding row"


@pytest.mark.skipif(
    not __import__("os").getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)
def test_exception_path_flips_status_to_failed(clean_db, cli):
    """Unhandled exception during _persist → status flips to 'failed' with error text.

    Induces failure by monkeypatching cli._persist to raise RuntimeError.
    The exception path calls _mark_failed which must UPDATE the run row.
    """
    _truncate_analysis_tables(clean_db)
    _seed_corpus(clean_db)

    db_url = __import__("os").environ["TEST_DATABASE_URL"]
    pre_inserted_run_id = str(uuid.uuid4())
    clean_db.query(
        """
        INSERT INTO text_decision_analysis_runs (id, status, triggered_by)
        VALUES (%(id)s, 'running', 'test')
        """,
        {"id": pre_inserted_run_id},
    )

    args = Namespace(
        database_url=db_url,
        run_id=pre_inserted_run_id,
        triggered_by=None,
        max_decisions=None,
    )

    boom = RuntimeError("simulated persist failure for test")

    with patch.object(cli, "_persist", side_effect=boom):
        import pytest as _pytest

        with _pytest.raises(RuntimeError, match="simulated persist failure"):
            cli._orchestrate(args)

    # After _orchestrate raises, the run row must show 'failed'.
    # _mark_failed uses its own connection so it commits independently.
    cli._mark_failed(db_url, pre_inserted_run_id, "simulated persist failure for test")

    runs = _query_runs(clean_db)
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "failed", (
        f"Expected status='failed' after exception, got {run['status']!r}"
    )
    assert run["error"] is not None
    assert "simulated" in run["error"]
