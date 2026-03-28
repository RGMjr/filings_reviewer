"""
Unit tests for scripts/apply_migrations.py

Tests ledger-aware migration logic using mocked DatabaseAdapter.
"""

import hashlib
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure project root is on path so scripts/ is importable
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.apply_migrations import (  # noqa: E402
    MIGRATIONS,
    _checksum,
    apply_migration,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_db(ledger_rows: dict[str, str] | None = None):
    """
    Build a mock DatabaseAdapter.

    ledger_rows maps migration_name -> checksum (already-applied entries).
    """
    ledger_rows = ledger_rows or {}
    db = MagicMock()

    def fake_query(sql, params=None):
        if params and "id" in params:
            name = params["id"]
            if name in ledger_rows:
                return [{"checksum": ledger_rows[name]}]
        return []

    db.query.side_effect = fake_query

    @contextmanager
    def fake_get_connection():
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        yield conn

    db.get_connection.side_effect = fake_get_connection
    return db


def write_sql_files(tmp_path: Path, names: list[str], content: str = "-- sql\n") -> Path:
    """Write stub SQL files and return the directory."""
    for name in names:
        (tmp_path / name).write_text(content)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests for _checksum
# ---------------------------------------------------------------------------


def test_checksum_is_sha256():
    sql = "SELECT 1;"
    expected = hashlib.sha256(sql.encode()).hexdigest()
    assert _checksum(sql) == expected


# ---------------------------------------------------------------------------
# Tests for apply_migration
# ---------------------------------------------------------------------------


def test_first_run_applies_all(tmp_path):
    """Fresh ledger: all 13 migrations should be applied."""
    sql_dir = write_sql_files(tmp_path, MIGRATIONS)
    db = make_db()  # empty ledger

    results = []
    for name in MIGRATIONS:
        result = apply_migration(db, sql_dir, name)
        results.append(result)

    assert all(r == "applied" for r in results)
    # get_connection called once per migration (for apply + ledger insert)
    assert db.get_connection.call_count == len(MIGRATIONS)


def test_second_run_is_noop(tmp_path):
    """Pre-populated ledger: all migrations should be skipped."""
    sql_content = "-- migration sql\n"
    sql_dir = write_sql_files(tmp_path, MIGRATIONS, sql_content)
    chk = _checksum(sql_content)

    # Ledger already has all migrations
    ledger = {name: chk for name in MIGRATIONS}
    db = make_db(ledger_rows=ledger)

    results = []
    for name in MIGRATIONS:
        result = apply_migration(db, sql_dir, name)
        results.append(result)

    assert all(r == "skipped" for r in results)
    # No DB writes should have occurred
    db.get_connection.assert_not_called()


def test_checksum_mismatch_raises(tmp_path):
    """Ledger has a different checksum: should raise RuntimeError."""
    name = MIGRATIONS[0]
    (tmp_path / name).write_text("-- current sql\n")

    # Ledger has a different checksum (file was altered)
    db = make_db(ledger_rows={name: "deadbeef" * 8})

    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        apply_migration(db, tmp_path, name)


def test_dry_run_makes_no_changes(tmp_path):
    """Dry-run mode: no DB writes, still returns 'applied' for unapplied migrations."""
    sql_dir = write_sql_files(tmp_path, MIGRATIONS)
    db = make_db()  # empty ledger

    results = []
    for name in MIGRATIONS:
        result = apply_migration(db, sql_dir, name, dry_run=True)
        results.append(result)

    assert all(r == "applied" for r in results)
    # No actual DB writes in dry-run
    db.get_connection.assert_not_called()


def test_partial_ledger_resumes(tmp_path):
    """Ledger has first 6 migrations; only the remaining 7 should be applied."""
    sql_content = "-- sql\n"
    sql_dir = write_sql_files(tmp_path, MIGRATIONS, sql_content)
    chk = _checksum(sql_content)

    already_applied = set(MIGRATIONS[:6])
    ledger = {name: chk for name in already_applied}
    db = make_db(ledger_rows=ledger)

    results = {}
    for name in MIGRATIONS:
        results[name] = apply_migration(db, sql_dir, name)

    for name in MIGRATIONS[:6]:
        assert results[name] == "skipped", f"{name} should be skipped"
    for name in MIGRATIONS[6:]:
        assert results[name] == "applied", f"{name} should be applied"

    # get_connection called only for the 7 newly applied migrations
    assert db.get_connection.call_count == len(MIGRATIONS) - 6
