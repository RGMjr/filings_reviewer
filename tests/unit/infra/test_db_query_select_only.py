"""Unit tests for the SELECT-only guard on DatabaseAdapter.query.

Catches the easy misuse where a developer reaches for `db.query` for an
INSERT/UPDATE/DELETE and gets an opaque psycopg error instead of a useful
"use db.execute" message. See `_reject_non_select` in src/infra/db.py.
"""

from __future__ import annotations

import pytest

from src.infra.db import _reject_non_select


class TestRejectNonSelect:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM filings",
            "  SELECT 1",
            "SELECT id FROM v2_documents WHERE doc_id = %(id)s",
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "INSERT INTO t (a) VALUES (1) RETURNING id",
            "UPDATE t SET a = 1 WHERE id = 2 RETURNING *",
            "DELETE FROM t WHERE id = 3 RETURNING id",
            "-- a leading comment\nSELECT 1",
            "/* block */ SELECT 1",
            "",
        ],
    )
    def test_allowed_statements(self, sql: str) -> None:
        # Should not raise
        _reject_non_select(sql)

    @pytest.mark.parametrize(
        ("sql", "verb"),
        [
            ("INSERT INTO t (a) VALUES (1)", "INSERT"),
            ("  insert into t values (1)", "INSERT"),
            ("UPDATE t SET a = 1 WHERE id = 2", "UPDATE"),
            ("DELETE FROM t WHERE id = 3", "DELETE"),
            ("-- comment\nINSERT INTO t (a) VALUES (1)", "INSERT"),
            ("/* leading block */\nUPDATE t SET a = 1", "UPDATE"),
        ],
    )
    def test_blocked_statements(self, sql: str, verb: str) -> None:
        with pytest.raises(ValueError, match=f"SELECT-only.*{verb}"):
            _reject_non_select(sql)

    def test_error_message_points_to_execute(self) -> None:
        with pytest.raises(ValueError, match=r"db\.execute"):
            _reject_non_select("DELETE FROM t WHERE id = 1")
