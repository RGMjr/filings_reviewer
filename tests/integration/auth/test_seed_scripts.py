"""Integration tests for scripts/seed_auth_users.py and scripts/seed_auth_legacy_aliases.py.

Each test cleans auth tables before running so tests are isolated. The
importlib pattern mirrors tests/integration/test_onboard_tickers_cli.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SEED_USERS_SCRIPT = PROJECT_ROOT / "scripts" / "seed_auth_users.py"
SEED_ALIASES_SCRIPT = PROJECT_ROOT / "scripts" / "seed_auth_legacy_aliases.py"


# ---------------------------------------------------------------------------
# Script loaders (importlib pattern)
# ---------------------------------------------------------------------------


def _load_module(script_path: Path, mod_name: str):
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def users_cli():
    return _load_module(SEED_USERS_SCRIPT, "seed_auth_users_integration")


@pytest.fixture(scope="module")
def aliases_cli():
    return _load_module(SEED_ALIASES_SCRIPT, "seed_auth_legacy_aliases_integration")


# ---------------------------------------------------------------------------
# Per-test auth table cleanup fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_db(test_db_adapter):
    """Yield the test DB adapter with auth tables truncated before/after each test.

    The shared clean_db fixture does not cover auth tables, so we manage them
    here to keep tests isolated.
    """

    def _truncate(adapter):
        with adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET CONSTRAINTS ALL DEFERRED")
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        TRUNCATE TABLE admin_audit_log CASCADE;
                        TRUNCATE TABLE auth_legacy_aliases CASCADE;
                        TRUNCATE TABLE auth_access_entries CASCADE;
                        TRUNCATE TABLE auth_sessions CASCADE;
                        TRUNCATE TABLE auth_users CASCADE;
                    EXCEPTION WHEN undefined_table THEN
                        NULL;
                    END $$;
                    """
                )
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

    _truncate(test_db_adapter)
    yield test_db_adapter
    _truncate(test_db_adapter)


# ---------------------------------------------------------------------------
# seed_auth_users.py tests
# ---------------------------------------------------------------------------


class TestSeedAuthUsers:
    def test_default_seeds_three_users(self, auth_db, users_cli, monkeypatch):
        """Default invocation inserts the 3 spec users."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])

        rc = users_cli.main()

        assert rc == 0
        rows = auth_db.query(
            "SELECT normalized_email, role, account_status FROM auth_users ORDER BY normalized_email"
        )
        emails = [r["normalized_email"] for r in rows]
        assert "rgmarkey@gmail.com" in emails
        assert "rob.markey@cmasb.org" in emails
        assert "mayujoiner@gmail.com" in emails
        assert len(rows) == 3

        # Roles
        by_email = {r["normalized_email"]: r for r in rows}
        assert by_email["rgmarkey@gmail.com"]["role"] == "admin"
        assert by_email["rob.markey@cmasb.org"]["role"] == "admin"
        assert by_email["mayujoiner@gmail.com"]["role"] == "reviewer"

        # All active
        for r in rows:
            assert r["account_status"] == "active"

    def test_default_writes_access_entries(self, auth_db, users_cli, monkeypatch):
        """Default invocation also populates auth_access_entries."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])

        users_cli.main()

        rows = auth_db.query(
            "SELECT normalized_email, intended_role, status FROM auth_access_entries "
            "ORDER BY normalized_email"
        )
        assert len(rows) == 3
        by_email = {r["normalized_email"]: r for r in rows}
        assert by_email["rgmarkey@gmail.com"]["intended_role"] == "admin"
        assert by_email["rgmarkey@gmail.com"]["status"] == "approved"
        assert by_email["mayujoiner@gmail.com"]["intended_role"] == "reviewer"

    def test_default_idempotent(self, auth_db, users_cli, monkeypatch):
        """Running default twice yields same 3 users — no duplicates, no errors."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])

        rc1 = users_cli.main()
        rc2 = users_cli.main()

        assert rc1 == 0
        assert rc2 == 0
        rows = auth_db.query("SELECT normalized_email FROM auth_users")
        assert len(rows) == 3

    def test_default_writes_audit_log_on_insert(self, auth_db, users_cli, monkeypatch):
        """First run writes audit log entries for each new user."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])

        users_cli.main()

        rows = auth_db.query(
            "SELECT action_type, target_entity, before_state, after_state "
            "FROM admin_audit_log WHERE action_type = 'seed_users' "
            "ORDER BY target_entity"
        )
        assert len(rows) == 3
        for r in rows:
            assert r["before_state"] is None  # new rows have no before state
            assert r["after_state"] is not None

    def test_default_no_audit_log_on_second_run(self, auth_db, users_cli, monkeypatch):
        """Second run (no changes) does not write new audit log entries."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])

        users_cli.main()
        count_after_first = auth_db.query("SELECT COUNT(*) AS n FROM admin_audit_log")[0]["n"]

        users_cli.main()
        count_after_second = auth_db.query("SELECT COUNT(*) AS n FROM admin_audit_log")[0]["n"]

        assert count_after_first == count_after_second

    def test_add_new_user(self, auth_db, users_cli, monkeypatch):
        """--add inserts a 4th user."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)

        # Seed the 3 spec users first.
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])
        users_cli.main()

        # Add a 4th.
        monkeypatch.setattr(
            "sys.argv",
            ["seed_auth_users.py", "--add", "test@example.com", "reviewer", "Test User"],
        )
        rc = users_cli.main()
        assert rc == 0

        rows = auth_db.query(
            "SELECT normalized_email, role FROM auth_users ORDER BY normalized_email"
        )
        assert len(rows) == 4
        by_email = {r["normalized_email"]: r for r in rows}
        assert "test@example.com" in by_email
        assert by_email["test@example.com"]["role"] == "reviewer"

    def test_remove_user_soft_deletes(self, auth_db, users_cli, monkeypatch):
        """--remove sets account_status='disabled'; user row is not deleted."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)

        # Seed + add test user.
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])
        users_cli.main()
        monkeypatch.setattr(
            "sys.argv",
            ["seed_auth_users.py", "--add", "test@example.com", "reviewer", "Test User"],
        )
        users_cli.main()

        # Remove the test user.
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py", "--remove", "test@example.com"])
        rc = users_cli.main()
        assert rc == 0

        rows = auth_db.query(
            "SELECT account_status, disabled_at FROM auth_users "
            "WHERE normalized_email = 'test@example.com'"
        )
        assert len(rows) == 1
        assert rows[0]["account_status"] == "disabled"
        assert rows[0]["disabled_at"] is not None

    def test_add_invalid_role_returns_error(self, auth_db, users_cli, monkeypatch):
        """--add with an invalid role returns non-zero exit code."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr(
            "sys.argv",
            ["seed_auth_users.py", "--add", "test@example.com", "superadmin", "Test User"],
        )
        rc = users_cli.main()
        assert rc != 0

    def test_list_flag(self, auth_db, users_cli, monkeypatch, capsys):
        """--list prints users without error."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])
        users_cli.main()

        monkeypatch.setattr("sys.argv", ["seed_auth_users.py", "--list"])
        rc = users_cli.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "rgmarkey@gmail.com" in out
        assert "admin" in out


# ---------------------------------------------------------------------------
# seed_auth_legacy_aliases.py tests
# ---------------------------------------------------------------------------


class TestSeedAuthLegacyAliases:
    def _seed_users(self, auth_db, users_cli, monkeypatch):
        """Helper: seed the 3 spec users (needed for alias tests)."""
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_users.py"])
        users_cli.main()

    def test_default_seeds_two_aliases(self, auth_db, users_cli, aliases_cli, monkeypatch):
        """Default invocation inserts the 2 spec aliases."""
        self._seed_users(auth_db, users_cli, monkeypatch)
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_legacy_aliases.py"])

        rc = aliases_cli.main()

        assert rc == 0
        rows = auth_db.query(
            "SELECT legacy_reviewer_string, target_email, active "
            "FROM auth_legacy_aliases ORDER BY legacy_reviewer_string"
        )
        assert len(rows) == 2
        by_legacy = {r["legacy_reviewer_string"]: r for r in rows}
        assert "Mayu" in by_legacy
        assert "RGM" in by_legacy
        assert by_legacy["RGM"]["target_email"] == "rgmarkey@gmail.com"
        assert by_legacy["Mayu"]["target_email"] == "mayujoiner@gmail.com"
        assert by_legacy["RGM"]["active"] is True
        assert by_legacy["Mayu"]["active"] is True

    def test_default_idempotent(self, auth_db, users_cli, aliases_cli, monkeypatch):
        """Running default twice yields same 2 aliases — no duplicates, no errors."""
        self._seed_users(auth_db, users_cli, monkeypatch)
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr("sys.argv", ["seed_auth_legacy_aliases.py"])

        rc1 = aliases_cli.main()
        rc2 = aliases_cli.main()

        assert rc1 == 0
        assert rc2 == 0
        rows = auth_db.query("SELECT legacy_reviewer_string FROM auth_legacy_aliases")
        assert len(rows) == 2

    def test_add_alias_requires_existing_user(self, auth_db, users_cli, aliases_cli, monkeypatch):
        """--add errors when the target email is not found in auth_users."""
        self._seed_users(auth_db, users_cli, monkeypatch)
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr(
            "sys.argv",
            ["seed_auth_legacy_aliases.py", "--add", "NEWLEG", "nonexistent@example.com"],
        )
        with pytest.raises(SystemExit) as exc_info:
            aliases_cli.main()
        assert exc_info.value.code != 0

    def test_add_alias_for_existing_user(self, auth_db, users_cli, aliases_cli, monkeypatch):
        """--add creates a new alias when the target user exists."""
        self._seed_users(auth_db, users_cli, monkeypatch)
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
        monkeypatch.setattr(
            "sys.argv",
            ["seed_auth_legacy_aliases.py", "--add", "ROB", "rob.markey@cmasb.org"],
        )
        rc = aliases_cli.main()
        assert rc == 0

        rows = auth_db.query(
            "SELECT target_email FROM auth_legacy_aliases WHERE legacy_reviewer_string = 'ROB'"
        )
        assert len(rows) == 1
        assert rows[0]["target_email"] == "rob.markey@cmasb.org"

    def test_remove_alias_hard_deletes(self, auth_db, users_cli, aliases_cli, monkeypatch):
        """--remove hard-deletes the alias row."""
        self._seed_users(auth_db, users_cli, monkeypatch)
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)

        # Seed the 2 spec aliases.
        monkeypatch.setattr("sys.argv", ["seed_auth_legacy_aliases.py"])
        aliases_cli.main()

        # Remove one.
        monkeypatch.setattr("sys.argv", ["seed_auth_legacy_aliases.py", "--remove", "RGM"])
        rc = aliases_cli.main()
        assert rc == 0

        rows = auth_db.query("SELECT legacy_reviewer_string FROM auth_legacy_aliases")
        legacy_strings = [r["legacy_reviewer_string"] for r in rows]
        assert "RGM" not in legacy_strings
        assert "Mayu" in legacy_strings

    def test_list_flag(self, auth_db, users_cli, aliases_cli, monkeypatch, capsys):
        """--list prints aliases without error."""
        self._seed_users(auth_db, users_cli, monkeypatch)
        monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)

        monkeypatch.setattr("sys.argv", ["seed_auth_legacy_aliases.py"])
        aliases_cli.main()

        monkeypatch.setattr("sys.argv", ["seed_auth_legacy_aliases.py", "--list"])
        rc = aliases_cli.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "RGM" in out
        assert "Mayu" in out
