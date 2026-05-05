"""Integration tests for scripts/auth_readiness_report.py.

Loads the script via importlib (mirrors test_seed_scripts.py) and exercises
all six report sections plus the --check exit semantics. Auth tables are
truncated before/after each test so cases are independent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "auth_readiness_report.py"
SEED_USERS_SCRIPT = PROJECT_ROOT / "scripts" / "seed_auth_users.py"
SEED_ALIASES_SCRIPT = PROJECT_ROOT / "scripts" / "seed_auth_legacy_aliases.py"


# ---------------------------------------------------------------------------
# Script loaders
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
def cli():
    return _load_module(SCRIPT_PATH, "auth_readiness_report_integration")


@pytest.fixture(scope="module")
def users_cli():
    return _load_module(SEED_USERS_SCRIPT, "seed_auth_users_integration_for_readiness")


@pytest.fixture(scope="module")
def aliases_cli():
    return _load_module(SEED_ALIASES_SCRIPT, "seed_auth_legacy_aliases_integration_for_readiness")


# ---------------------------------------------------------------------------
# Per-test cleanup
# ---------------------------------------------------------------------------


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
                    TRUNCATE TABLE feature_flags CASCADE;
                EXCEPTION WHEN undefined_table THEN
                    NULL;
                END $$;
                """
            )
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.fixture
def auth_db(test_db_adapter):
    _truncate(test_db_adapter)
    yield test_db_adapter
    _truncate(test_db_adapter)


@pytest.fixture(autouse=True)
def _clean_bypass_env(monkeypatch):
    """Ensure dev-bypass guard sees a clean env unless a test sets it."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("AUTH_DEV_BYPASS", raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_db_text_report(auth_db, cli):
    report = cli.build_report(auth_db)
    text = cli._format_text(report)

    assert "Allowlisted users" in text
    assert "(none — auth_access_entries is empty)" in text
    assert "Active sessions: 0" in text
    assert "(no rows in feature_flags" in text
    assert "Production dev-bypass guard: PASS" in text


def test_empty_db_check_fails(auth_db, cli):
    report = cli.build_report(auth_db)
    ready, reasons = cli.evaluate_readiness(report)

    assert ready is False
    assert any("No allowlisted users" in r for r in reasons)


def test_empty_db_json_shape(auth_db, cli):
    report = cli.build_report(auth_db)
    payload = json.loads(cli._format_json(report))

    assert set(payload.keys()) == {
        "allowlisted",
        "users",
        "active_sessions",
        "legacy_aliases",
        "flags",
        "dev_bypass_guard",
    }
    assert payload["allowlisted"] == []
    assert payload["users"] == []
    assert payload["active_sessions"] == 0
    assert payload["legacy_aliases"] == []
    assert payload["flags"] == []
    assert payload["dev_bypass_guard"]["status"] == "PASS"


def test_populated_json_shape(auth_db, cli, users_cli, aliases_cli):
    """--json output shape is correct with seeded data (populated case)."""
    for u in users_cli.SEED_USERS:
        users_cli.upsert_user(auth_db, u["email"], u["role"], u["display_name"], verbose=False)
    for a in aliases_cli.SEED_ALIASES:
        aliases_cli.upsert_alias(
            auth_db, a["legacy_reviewer_string"], a["target_email"], verbose=False
        )

    report = cli.build_report(auth_db)
    payload = json.loads(cli._format_json(report))

    assert set(payload.keys()) == {
        "allowlisted",
        "users",
        "active_sessions",
        "legacy_aliases",
        "flags",
        "dev_bypass_guard",
    }
    assert len(payload["allowlisted"]) == 3
    assert all(
        {"normalized_email", "intended_role", "status", "created_at"} <= set(r)
        for r in payload["allowlisted"]
    )
    assert len(payload["users"]) == 3
    assert all(
        {"normalized_email", "display_name", "first_login_at", "last_login_at", "account_status"}
        <= set(r)
        for r in payload["users"]
    )
    assert payload["active_sessions"] == 0
    assert len(payload["legacy_aliases"]) == 2
    assert all(
        {"legacy_reviewer_string", "target_email", "active", "created_at"} <= set(r)
        for r in payload["legacy_aliases"]
    )
    assert payload["flags"] == []
    assert set(payload["dev_bypass_guard"].keys()) == {"status", "app_env", "auth_dev_bypass"}
    assert payload["dev_bypass_guard"]["status"] == "PASS"


def test_post_seed_check_passes(auth_db, cli, users_cli, aliases_cli):
    """Run the seed scripts (their main paths), then evaluate readiness."""
    # Seed users via the script's default code path.
    for u in users_cli.SEED_USERS:
        users_cli.upsert_user(auth_db, u["email"], u["role"], u["display_name"], verbose=False)
    # Seed aliases via the script's default code path.
    for a in aliases_cli.SEED_ALIASES:
        aliases_cli.upsert_alias(
            auth_db,
            a["legacy_reviewer_string"],
            a["target_email"],
            verbose=False,
        )

    report = cli.build_report(auth_db)

    assert len(report["allowlisted"]) == 3
    assert len(report["users"]) == 3
    assert len(report["legacy_aliases"]) == 2
    assert report["active_sessions"] == 0
    # No feature_flags rows yet
    assert report["flags"] == []
    assert report["dev_bypass_guard"]["status"] == "PASS"

    ready, reasons = cli.evaluate_readiness(report)
    assert ready is True, f"unexpected NOT READY reasons: {reasons}"


def test_first_login_simulation(auth_db, cli):
    """Insert an auth_users row representing a successful first login."""
    with auth_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_access_entries (normalized_email, intended_role)
                VALUES ('alice@example.com', 'reviewer')
                """
            )
            cur.execute(
                """
                INSERT INTO auth_users
                    (normalized_email, role, display_name, google_sub,
                     first_login_at, last_login_at)
                VALUES
                    ('alice@example.com', 'reviewer', 'Alice', 'sub-1',
                     NOW() - INTERVAL '2 days', NOW())
                """
            )
        conn.commit()

    report = cli.build_report(auth_db)
    user_row = next(u for u in report["users"] if u["normalized_email"] == "alice@example.com")
    assert user_row["first_login_at"] is not None
    assert user_row["last_login_at"] is not None
    assert user_row["account_status"] == "active"

    text = cli._format_text(report)
    assert "alice@example.com" in text
    # last_login_at NOT rendered as 'never'
    alice_line = next(
        line for line in text.splitlines() if "alice@example.com" in line and "active" in line
    )
    assert "never" not in alice_line.split("active")[1]


def test_disabled_user_does_not_block_check(auth_db, cli):
    with auth_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_access_entries (normalized_email, intended_role)
                VALUES ('bob@example.com', 'reviewer')
                """
            )
            cur.execute(
                """
                INSERT INTO auth_users
                    (normalized_email, role, account_status, disabled_at)
                VALUES
                    ('bob@example.com', 'reviewer', 'disabled', NOW())
                """
            )
        conn.commit()

    report = cli.build_report(auth_db)
    user_row = next(u for u in report["users"] if u["normalized_email"] == "bob@example.com")
    assert user_row["account_status"] == "disabled"

    ready, reasons = cli.evaluate_readiness(report)
    assert ready is True, f"disabled user should not block --check; reasons: {reasons}"


def test_expired_active_flag_fails_check(auth_db, cli):
    with auth_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_access_entries (normalized_email, intended_role)
                VALUES ('carol@example.com', 'admin')
                """
            )
            cur.execute(
                """
                INSERT INTO feature_flags (key, value, expires_at)
                VALUES ('legacy_emergency_access_enabled', 'true',
                        NOW() - INTERVAL '1 minute')
                """
            )
        conn.commit()

    report = cli.build_report(auth_db)
    flag_row = next(f for f in report["flags"] if f["key"] == "legacy_emergency_access_enabled")
    assert flag_row["expired"] is True
    assert flag_row["value"] == "true"

    ready, reasons = cli.evaluate_readiness(report)
    assert ready is False
    assert any("legacy_emergency_access_enabled" in r for r in reasons)


def test_dev_bypass_guard_fail(auth_db, cli, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_BYPASS", "1")

    # Seed a valid allowlist row so the only failure is the guard.
    with auth_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_access_entries (normalized_email, intended_role)
                VALUES ('dave@example.com', 'admin')
                """
            )
        conn.commit()

    report = cli.build_report(auth_db)
    assert report["dev_bypass_guard"]["status"] == "FAIL"
    assert report["dev_bypass_guard"]["app_env"] == "production"
    assert report["dev_bypass_guard"]["auth_dev_bypass"] == "1"

    ready, reasons = cli.evaluate_readiness(report)
    assert ready is False
    assert any("Dev-bypass guard FAIL" in r for r in reasons)


def test_active_session_counted(auth_db, cli):
    with auth_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_users (normalized_email, role)
                VALUES ('eve@example.com', 'reviewer')
                RETURNING id
                """
            )
            user_id = cur.fetchone()["id"]
            # One live session, one expired
            cur.execute(
                """
                INSERT INTO auth_sessions (user_id, expires_at)
                VALUES (%s, NOW() + INTERVAL '1 hour'),
                       (%s, NOW() - INTERVAL '1 hour')
                """,
                (user_id, user_id),
            )
        conn.commit()

    report = cli.build_report(auth_db)
    assert report["active_sessions"] == 1


def test_main_check_returns_zero_when_ready(auth_db, cli, users_cli, monkeypatch, capsys):
    """Drive main(--check) end-to-end and assert exit 0 on a seeded DB."""
    for u in users_cli.SEED_USERS:
        users_cli.upsert_user(auth_db, u["email"], u["role"], u["display_name"], verbose=False)

    monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
    monkeypatch.setattr(sys, "argv", ["auth_readiness_report.py", "--check"])

    rc = cli.main()
    captured = capsys.readouterr()
    assert rc == 0, f"unexpected NOT READY output: {captured.err}"
    assert captured.out == ""
    assert not any("NOT READY" in line for line in captured.err.splitlines())


def test_main_check_returns_one_on_empty_db(auth_db, cli, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", auth_db.connection_string)
    monkeypatch.setattr(sys, "argv", ["auth_readiness_report.py", "--check"])

    rc = cli.main()
    captured = capsys.readouterr()
    assert rc == 1
    assert "NOT READY" in captured.err


def test_main_returns_two_when_database_url_missing(cli, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["auth_readiness_report.py"])

    rc = cli.main()
    captured = capsys.readouterr()
    assert rc == 2
    assert "DATABASE_URL" in captured.err
