"""Integration tests for scripts/link_text_recommendation_to_pr.py.

Covers the four specified behaviors:
  - Happy path: NULL pr_number → populated after script runs.
  - Refuse-overwrite: already-set row without --force exits 3 and leaves value.
  - Force-overwrite: --force replaces the existing pr_number.
  - Missing-row: no matching row exits 2 with a clear error.

Requires TEST_DATABASE_URL.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set",
    ),
]

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "link_text_recommendation_to_pr.py"

_REVIEWER_ID = "test-engineer@example.com"
_METRIC_ID = "cm_active_customers_total"
_RULE = "exclusion_pattern"
_DECISION_KEY = "accounts receivable"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "link_text_recommendation_to_pr_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script_module()


def _seed_decision_row(
    db_url: str,
    *,
    metric_id: str = _METRIC_ID,
    rule: str = _RULE,
    decision_key: str = _DECISION_KEY,
    reviewer_id: str = _REVIEWER_ID,
    pr_number: int | None = None,
    pr_url: str | None = None,
) -> str:
    """Insert a text_pattern_recommendation_decisions row; return its UUID."""
    row_id = str(uuid.uuid4())
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.row_factory = dict_row
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO text_pattern_recommendation_decisions
                    (id, metric_id, rule, decision_key, decision, reviewer_id,
                     pr_number, pr_url)
                VALUES
                    (%(id)s, %(metric_id)s, %(rule)s, %(decision_key)s,
                     'accepted', %(reviewer_id)s, %(pr_number)s, %(pr_url)s)
                ON CONFLICT (metric_id, rule, decision_key, reviewer_id)
                    DO UPDATE SET
                        pr_number  = EXCLUDED.pr_number,
                        pr_url     = EXCLUDED.pr_url,
                        updated_at = NOW()
                RETURNING id::text
                """,
                {
                    "id": row_id,
                    "metric_id": metric_id,
                    "rule": rule,
                    "decision_key": decision_key,
                    "reviewer_id": reviewer_id,
                    "pr_number": pr_number,
                    "pr_url": pr_url,
                },
            )
            returned = cur.fetchone()
    return returned["id"]  # may differ from row_id on conflict-update


def _fetch_row(
    db_url: str,
    *,
    metric_id: str = _METRIC_ID,
    rule: str = _RULE,
    decision_key: str = _DECISION_KEY,
    reviewer_id: str = _REVIEWER_ID,
) -> dict | None:
    with psycopg.connect(db_url) as conn:
        conn.row_factory = dict_row
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pr_number, pr_url
                  FROM text_pattern_recommendation_decisions
                 WHERE metric_id   = %(metric_id)s
                   AND rule        = %(rule)s
                   AND decision_key = %(decision_key)s
                   AND reviewer_id  = %(reviewer_id)s
                """,
                {
                    "metric_id": metric_id,
                    "rule": rule,
                    "decision_key": decision_key,
                    "reviewer_id": reviewer_id,
                },
            )
            return cur.fetchone()


def _delete_row(
    db_url: str,
    *,
    metric_id: str = _METRIC_ID,
    rule: str = _RULE,
    decision_key: str = _DECISION_KEY,
    reviewer_id: str = _REVIEWER_ID,
) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM text_pattern_recommendation_decisions
                 WHERE metric_id   = %(metric_id)s
                   AND rule        = %(rule)s
                   AND decision_key = %(decision_key)s
                   AND reviewer_id  = %(reviewer_id)s
                """,
                {
                    "metric_id": metric_id,
                    "rule": rule,
                    "decision_key": decision_key,
                    "reviewer_id": reviewer_id,
                },
            )


def _run_script(db_url: str, extra_args: list[str]) -> subprocess.CompletedProcess:
    """Run the script via subprocess so exit-code behavior is testable."""
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--decision-key",
            _DECISION_KEY,
            "--metric-id",
            _METRIC_ID,
            "--rule",
            _RULE,
            "--reviewer-id",
            _REVIEWER_ID,
            "--database-url",
            db_url,
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def cleanup(test_db_url):
    """Delete the test row before and after each test for isolation."""
    _delete_row(test_db_url)
    yield
    _delete_row(test_db_url)


@pytest.fixture(scope="session")
def test_db_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


class TestHappyPath:
    def test_null_pr_number_gets_populated(self, test_db_url):
        _seed_decision_row(test_db_url, pr_number=None)

        result = _run_script(test_db_url, ["--pr-number", "501"])

        assert result.returncode == 0, result.stderr
        assert "Linked" in result.stdout
        assert "PR #501" in result.stdout

        row = _fetch_row(test_db_url)
        assert row is not None
        assert row["pr_number"] == 501
        assert row["pr_url"] == "https://github.com/RGMjr/filings_reviewer/pull/501"

    def test_explicit_pr_url_is_stored(self, test_db_url):
        _seed_decision_row(test_db_url, pr_number=None)
        custom_url = "https://github.com/org/repo/pull/999"

        result = _run_script(
            test_db_url,
            ["--pr-number", "999", "--pr-url", custom_url],
        )

        assert result.returncode == 0, result.stderr
        row = _fetch_row(test_db_url)
        assert row is not None
        assert row["pr_url"] == custom_url

    def test_idempotent_when_run_twice_with_same_values(self, test_db_url):
        _seed_decision_row(test_db_url, pr_number=None)

        result1 = _run_script(test_db_url, ["--pr-number", "501"])
        assert result1.returncode == 0

        # Second run — already has pr_number=501, no --force → exit 3.
        result2 = _run_script(test_db_url, ["--pr-number", "501"])
        assert result2.returncode == 3


class TestRefuseOverwrite:
    def test_exits_3_without_force(self, test_db_url):
        _seed_decision_row(test_db_url, pr_number=200)

        result = _run_script(test_db_url, ["--pr-number", "300"])

        assert result.returncode == 3
        assert "Refusing to overwrite" in result.stderr
        assert "pr_number=200" in result.stderr

    def test_original_value_preserved(self, test_db_url):
        _seed_decision_row(test_db_url, pr_number=200)
        _run_script(test_db_url, ["--pr-number", "300"])

        row = _fetch_row(test_db_url)
        assert row is not None
        assert row["pr_number"] == 200


class TestForceOverwrite:
    def test_force_replaces_existing_pr_number(self, test_db_url):
        _seed_decision_row(test_db_url, pr_number=200)

        result = _run_script(test_db_url, ["--pr-number", "300", "--force"])

        assert result.returncode == 0, result.stderr
        row = _fetch_row(test_db_url)
        assert row is not None
        assert row["pr_number"] == 300

    def test_force_on_null_row_also_succeeds(self, test_db_url):
        _seed_decision_row(test_db_url, pr_number=None)

        result = _run_script(test_db_url, ["--pr-number", "400", "--force"])

        assert result.returncode == 0, result.stderr
        row = _fetch_row(test_db_url)
        assert row is not None
        assert row["pr_number"] == 400


class TestMissingRow:
    def test_exits_2_when_row_absent(self, test_db_url):
        # No seed — row does not exist.
        result = _run_script(test_db_url, ["--pr-number", "501"])

        assert result.returncode == 2
        assert "no row found" in result.stderr

    def test_exits_2_when_reviewer_id_mismatch(self, test_db_url):
        _seed_decision_row(test_db_url, reviewer_id="someone-else@example.com")

        # Our _run_script uses _REVIEWER_ID = "test-engineer@example.com" which
        # won't match the row seeded with a different reviewer.
        result = _run_script(test_db_url, ["--pr-number", "501"])

        assert result.returncode == 2
