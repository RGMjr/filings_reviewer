"""Integration regression test for the Phase-2/3/4 since-anchor helpers.

These helpers all build SQL like:

    WHERE (%(ts)s IS NULL OR created_at > %(ts)s)

which throws `psycopg.errors.AmbiguousParameter` against a real Postgres
when ts=None — the planner cannot infer the parameter type from a NULL
literal in `IS NULL` + `>`. The fix is an explicit `::timestamptz` cast
on each parameter reference. Unit tests mock `db.query`, so they never
exercise this path; this test runs the actual SQL against
TEST_DATABASE_URL to catch a regression if the cast is ever stripped.

Triggered by a prod 500 on /v2/review/stats after Phase 4 deployed
(2026-05-01).
"""

from __future__ import annotations

import pytest

from src.infra.db import DatabaseAdapter


def test_count_image_decisions_since_handles_none(test_db_adapter: DatabaseAdapter) -> None:
    """ts=None must NOT raise AmbiguousParameter. Lifetime-totals branch."""
    result = test_db_adapter.count_image_decisions_since(None)
    assert set(result.keys()) == {"total", "positive", "negative"}
    # Empty DB or seed: counts must be non-negative ints.
    assert all(isinstance(v, int) and v >= 0 for v in result.values())


def test_count_text_decisions_since_handles_none(test_db_adapter: DatabaseAdapter) -> None:
    """ts=None must NOT raise. Returns plain int (lifetime total)."""
    result = test_db_adapter.count_text_decisions_since(None)
    assert isinstance(result, int)
    assert result >= 0


def test_rejection_reason_rollup_text_handles_none(
    test_db_adapter: DatabaseAdapter,
) -> None:
    """get_rejection_reason_rollup('text', since=None) must NOT raise."""
    rows = test_db_adapter.get_rejection_reason_rollup("text", since=None)
    assert isinstance(rows, list)
    for r in rows:
        assert "reason" in r
        assert "count" in r
        assert "percent" in r


def test_rejection_reason_rollup_image_handles_none(
    test_db_adapter: DatabaseAdapter,
) -> None:
    """get_rejection_reason_rollup('image', since=None) must NOT raise."""
    rows = test_db_adapter.get_rejection_reason_rollup("image", since=None)
    assert isinstance(rows, list)


def test_rejection_reason_rollup_rejects_unknown_side(
    test_db_adapter: DatabaseAdapter,
) -> None:
    with pytest.raises(ValueError, match="Unknown side"):
        test_db_adapter.get_rejection_reason_rollup("audio", since=None)
