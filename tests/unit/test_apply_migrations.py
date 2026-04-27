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
    _checksum_legacy,
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


def test_checksum_is_sha256_for_comment_free_sql():
    """When the SQL has no whole-line `--` comments, _checksum equals raw SHA-256."""
    sql = "SELECT 1;"
    expected = hashlib.sha256(sql.encode()).hexdigest()
    assert _checksum(sql) == expected


def test_checksum_strips_whole_line_comments():
    """Whole-line `--` comments are excluded from the hash.

    Comment-only edits to applied migration files (cluster-DDL markers,
    operator notes, doc fixes) MUST NOT trip the checksum guard.
    """
    sql_a = "-- header v1\nSELECT 1;\n"
    sql_b = "-- header v2 with totally different text\nSELECT 1;\n"
    sql_c = "    -- whitespace-prefixed comment\nSELECT 1;\n"
    assert _checksum(sql_a) == _checksum(sql_b)
    assert _checksum(sql_a) == _checksum(sql_c)


def test_checksum_preserves_inline_comments():
    """Inline trailing `--` comments stay in the hash.

    Only lines whose first non-whitespace token is `--` are dropped. A SQL
    statement with a trailing comment ('SELECT 1; -- note') is still part of
    the migration's semantic content.
    """
    sql_a = "SELECT 1; -- note one\n"
    sql_b = "SELECT 1; -- note two\n"
    assert _checksum(sql_a) != _checksum(sql_b)


def test_checksum_legacy_matches_raw_bytes():
    """_checksum_legacy is the pre-normalization raw-bytes hash, used by reconcile."""
    sql = "-- header\nSELECT 1;\n"
    expected = hashlib.sha256(sql.encode()).hexdigest()
    assert _checksum_legacy(sql) == expected
    # And: legacy differs from new when comments are present.
    assert _checksum_legacy(sql) != _checksum(sql)


# ---------------------------------------------------------------------------
# Tests for apply_migration
# ---------------------------------------------------------------------------


def test_first_run_applies_all(tmp_path):
    """Fresh ledger: all migrations should be applied."""
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

    # get_connection called only for newly applied migrations
    assert db.get_connection.call_count == len(MIGRATIONS) - 6


def test_migration_16_registered():
    """Migration 16 (8-K form_type fix) must be registered in MIGRATIONS."""
    assert "16_add_8k_form_type.sql" in MIGRATIONS
    # Must come after migration 15
    idx_15 = MIGRATIONS.index("15_rename_cohort_heatmap_to_parfait.sql")
    idx_16 = MIGRATIONS.index("16_add_8k_form_type.sql")
    assert idx_16 > idx_15


# ---------------------------------------------------------------------------
# Tests for the comment-stripping checksum rule + rule-transition self-heal
# (legacy-095)
# ---------------------------------------------------------------------------


def test_checksum_ignores_line_leading_comments():
    """Two SQL strings differing only in line-leading -- comments hash equally."""
    bare = "CREATE TABLE foo (id INT);\n"
    with_comments = (
        "-- header comment\n"
        "  -- indented marker\n"
        "CREATE TABLE foo (id INT);\n"
        "-- trailing footer\n"
    )
    assert _checksum(bare) == _checksum(with_comments)


def test_checksum_distinguishes_real_ddl_changes():
    """Two SQL strings differing in actual DDL hash to different checksums."""
    a = "CREATE TABLE foo (id INT);\n"
    b = "CREATE TABLE foo (id BIGINT);\n"
    assert _checksum(a) != _checksum(b)


def test_checksum_preserves_inline_trailing_comments():
    """Trailing -- after a statement is part of the line (not stripped)."""
    bare = "SELECT 1;\n"
    inline = "SELECT 1; -- note\n"
    # Spec: only line-leading -- lines are stripped. Inline -- after a
    # statement remains in the hashed content.
    assert _checksum(bare) != _checksum(inline)


def test_apply_migration_self_heals_rule_transition(tmp_path):
    """A ledger row with the pre-rule-change raw-byte hash is auto-reconciled."""
    name = "legacy_ledger.sql"
    sql = "-- header comment\nCREATE TABLE foo (id INT);\n"
    (tmp_path / name).write_text(sql)

    # Stored hash predates the comment-strip rule (raw bytes).
    stored = _checksum_legacy(sql)
    assert stored != _checksum(sql), "fixture must exercise the transition path"

    executed = []

    db = MagicMock()
    db.query.side_effect = lambda q, params=None: (
        [{"checksum": stored}] if params and params.get("id") == name else []
    )

    @contextmanager
    def fake_get_connection():
        conn = MagicMock()
        cur = MagicMock()
        cur.execute.side_effect = lambda q, params=None: executed.append((q, params))
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        yield conn

    db.get_connection.side_effect = fake_get_connection

    result = apply_migration(db, tmp_path, name)
    assert result == "skipped"

    update_calls = [
        (q, p) for q, p in executed if "UPDATE schema_migrations" in q
    ]
    assert len(update_calls) == 1, f"expected exactly one UPDATE, got {executed}"
    _, params = update_calls[0]
    assert params == {"checksum": _checksum(sql), "id": name}


def test_apply_migration_raises_when_neither_hash_matches(tmp_path):
    """Stored matches neither new-rule nor raw hash: existing RuntimeError fires."""
    name = "drifted.sql"
    sql = "-- header\nCREATE TABLE foo (id INT);\n"
    (tmp_path / name).write_text(sql)

    # Some unrelated stored value — file was actually modified post-apply.
    db = make_db(ledger_rows={name: "deadbeef" * 8})

    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        apply_migration(db, tmp_path, name)
