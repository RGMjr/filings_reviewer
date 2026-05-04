"""Regression test for the boot-time conditional auth blueprint registration.

Bug observed during Stage B activation 2026-05-04:
``is_enabled('google_login_enabled')`` was called from ``create_app()`` before
any Flask app context was active, so ``get_db()`` raised "Working outside of
application context" inside ``_read_flag_from_db``. The broad ``except`` in
that helper swallowed the error, the flag silently read False, and the auth
blueprint was never registered — even with the ``feature_flags`` row set to
``'true'`` in the DB.

Fix: wrap the boot-time check in ``with app.app_context():`` (``src/web/app.py``).
This file pins both the happy path (row=true → blueprint registered) AND the
default-off path (row absent → blueprint not registered) AND asserts that no
"Working outside of application context" warning fires during ``create_app``.
"""

from __future__ import annotations

import pytest


def _set_flag(adapter, value: str) -> None:
    adapter.execute(
        """
        INSERT INTO feature_flags (key, value)
        VALUES ('google_login_enabled', %(v)s)
        ON CONFLICT (key) DO UPDATE SET value=%(v)s, updated_at=NOW()
        """,
        {"v": value},
    )


def _delete_flag(adapter) -> None:
    adapter.execute("DELETE FROM feature_flags WHERE key='google_login_enabled'")


def _common_env(monkeypatch, adapter) -> None:
    monkeypatch.setenv("DATABASE_URL", adapter.connection_string)
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost/auth/callback")


def _make_app(adapter):
    from src.auth import feature_flags
    from src.web.app import create_app

    feature_flags._clear_cache_for_tests()

    return create_app(
        "testing",
        config_override={
            "DATABASE_URL": adapter.connection_string,
            "TESTING": True,
            "DB_POOL_ENABLED": False,
        },
    )


@pytest.fixture
def adapter(auth_db_clean):
    """Use the shared auth_db_clean fixture and clear our specific flag row."""
    _delete_flag(auth_db_clean)
    yield auth_db_clean
    _delete_flag(auth_db_clean)


def test_blueprint_registered_when_flag_true(adapter, monkeypatch, caplog):
    _set_flag(adapter, "true")
    _common_env(monkeypatch, adapter)

    with caplog.at_level("WARNING"):
        app = _make_app(adapter)

    assert "auth" in app.blueprints, f"auth_bp missing; registered={list(app.blueprints)}"

    # Critical: the bug used to log this warning. Pin it as a guard.
    bad = [
        r.getMessage()
        for r in caplog.records
        if "Working outside of application context" in r.getMessage()
    ]
    assert not bad, f"flag-read failing on app context: {bad}"


def test_blueprint_skipped_when_flag_false(adapter, monkeypatch):
    _set_flag(adapter, "false")
    _common_env(monkeypatch, adapter)

    app = _make_app(adapter)
    assert "auth" not in app.blueprints


def test_blueprint_skipped_when_flag_absent(adapter, monkeypatch):
    # adapter fixture already deleted the row.
    _common_env(monkeypatch, adapter)

    app = _make_app(adapter)
    assert "auth" not in app.blueprints
