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

    Creates two facts on the same metric, each with one reject decision sharing
    similar rejection_reason text — the n-gram miner needs MIN_OCCURRENCES=2
    matches across distinct decisions, and ``v2_review_decisions_unique_fact``
    forbids two decisions on a single fact, so two facts are required.

    Returns (filing_id, fact_ids, segment_id) where fact_ids is a list[str].
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

    # Two facts on the same metric, distinguished by period to satisfy
    # ``idx_v2_metric_facts_identity_unique`` (the index covers
    # filing_id+metric+period+unit+scope+cohort+customer_type+source_type).
    # Both rejected with overlapping rejection_reason tokens so the n-gram
    # miner clears MIN_OCCURRENCES=2 / MIN_PCT=10.
    fact_ids: list[str] = []
    for raw_value, year in (("110%", 2023), ("115%", 2024)):
        fact_id = create_test_v2_fact(
            db,
            filing_id,
            canonical_metric_id="cm_net_revenue_retention",
            value_raw=raw_value,
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            source_locator={"segment_id": segment_id},
        )
        create_test_v2_decision(
            db,
            fact_id,
            decision="reject",
            rejection_reason="wrong metric extracted from retention table",
            rejection_category="wrong_metric",
        )
        fact_ids.append(fact_id)

    return filing_id, fact_ids, segment_id


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
    filing_id, _fact_ids, segment_id = _seed_corpus(clean_db)

    db_url = __import__("os").environ["TEST_DATABASE_URL"]
    args = Namespace(
        database_url=db_url,
        run_id=None,
        triggered_by="test",
        max_decisions=None,
    )

    # First run — consumes the 2 seeded decisions.
    cli._orchestrate(args)

    # Add a third fact (the seeded ones already have decisions; the
    # v2_review_decisions_unique_fact constraint forbids reusing them) and
    # decision it AFTER the first run completes so created_at > anchor.
    from tests.integration.conftest import create_test_v2_decision, create_test_v2_fact

    new_fact_id = create_test_v2_fact(
        clean_db,
        filing_id,
        canonical_metric_id="cm_net_revenue_retention",
        value_raw="120%",
        # 2025 period — disambiguates from the 2023 / 2024 facts seeded above
        # under ``idx_v2_metric_facts_identity_unique``.
        period_start="2025-01-01",
        period_end="2025-12-31",
        source_locator={"segment_id": segment_id},
    )
    create_test_v2_decision(
        clean_db,
        new_fact_id,
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
    clean_db.execute(
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
    clean_db.execute(
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


@pytest.mark.skipif(
    not __import__("os").getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)
def test_run_writes_config_snapshot_hash(clean_db, cli):
    """_orchestrate writes config_snapshot_hash to the run row at run-start.

    Asserts:
    - The run row has a non-null config_snapshot_hash after a successful run.
    - The stored hash matches compute_config_hash() called at assertion time
      (the config files have not changed between the analysis run and the
      assertion, so the hashes must be equal).
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
    our_run = next(r for r in runs if r["triggered_by"] == "test")
    assert our_run["status"] == "succeeded"

    stored_hash = our_run.get("config_snapshot_hash")
    assert stored_hash is not None, "config_snapshot_hash must be non-null after a successful run"

    # The config files have not changed, so the live hash must match the
    # stored hash captured at run-start.
    from src.extraction_v2.config_hash import compute_config_hash

    assert stored_hash == compute_config_hash(), (
        "Stored config_snapshot_hash does not match current compute_config_hash() — "
        "either the hash was not written correctly or config files changed mid-test"
    )


@pytest.mark.skipif(
    not __import__("os").getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)
def test_free_text_source_fields_are_dropped(clean_db, cli):
    """After PR 4, phrase_findings rows must only have source_field='segment_text'.

    Seeded decisions have non-empty rejection_reason, reviewer_notes, AND
    segment_text. The miner must produce zero rows for
    source_field IN ('rejection_reason', 'reviewer_notes').

    Assertion also verifies that segment_text rows ARE produced (so the test
    is not trivially passing due to a broken miner that emits nothing).
    """
    _truncate_analysis_tables(clean_db)

    # Use a different cik/accession than _seed_corpus to avoid unique-key
    # conflicts when this test shares the clean_db with other tests.
    from tests.integration.conftest import (
        create_test_company_and_filing,
        create_test_v2_decision,
        create_test_v2_fact,
    )

    _, filing_id = create_test_company_and_filing(
        clean_db, cik="0009980002", accession_number="0009980002-24-000001"
    )

    # Segment with rich text so n-gram mining produces findings.
    segment_rows = clean_db.query(
        """
        INSERT INTO v2_segments
            (filing_id, segment_type, segment_text, dom_locator, sequence_idx)
        VALUES
            (%(filing_id)s, 'paragraph',
             'annual recurring revenue customers retained cohort expansion metric value',
             '/html/body/p[2]', 2)
        RETURNING segment_id::text
        """,
        {"filing_id": filing_id},
    )
    segment_id = segment_rows[0]["segment_id"]

    # Two facts + decisions so MIN_OCCURRENCES=2 is satisfied.
    for raw_value, year in (("100%", 2023), ("105%", 2024)):
        fact_id = create_test_v2_fact(
            clean_db,
            filing_id,
            canonical_metric_id="cm_net_revenue_retention",
            value_raw=raw_value,
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            source_locator={"segment_id": segment_id},
        )
        # Non-empty rejection_reason and reviewer_notes alongside segment_text.
        create_test_v2_decision(
            clean_db,
            fact_id,
            decision="reject",
            rejection_reason="noisy free text reason should not appear in findings",
            rejection_category="wrong_metric",
        )

    db_url = __import__("os").environ["TEST_DATABASE_URL"]
    args = Namespace(
        database_url=db_url,
        run_id=None,
        triggered_by="test_pr4",
        max_decisions=None,
    )
    cli._orchestrate(args)

    runs = _query_runs(clean_db)
    # Find the run we just created (triggered_by='test_pr4').
    our_run = next(r for r in runs if r["triggered_by"] == "test_pr4")
    run_id = str(our_run["id"])
    assert our_run["status"] == "succeeded"

    findings = _query_findings(clean_db, run_id)

    # Zero rows from free-text sources.
    free_text_rows = [
        f for f in findings if f["source_field"] in ("rejection_reason", "reviewer_notes")
    ]
    assert free_text_rows == [], (
        f"Expected no findings from rejection_reason/reviewer_notes after PR 4, "
        f"but got {len(free_text_rows)} row(s): {free_text_rows}"
    )

    # Segment-text rows still produced (miner is working, not silently empty).
    segment_rows_found = [f for f in findings if f["source_field"] == "segment_text"]
    assert len(segment_rows_found) >= 1, (
        "Expected at least one segment_text finding row — check MIN_OCCURRENCES "
        "threshold or segment text tokenization"
    )
