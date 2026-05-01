"""
Integration tests for src/auth/load_user.py — load_session_user middleware.

These tests exercise the before_request hook end-to-end through a minimal
Flask application. They mock ``lookup_session`` at the boundary so no real
DB connection is required, but they run the actual Flask request lifecycle
(including g initialisation) to confirm that ``g.user`` is populated
correctly.

Coverage:
- No cookie present → g.user is None
- Cookie present, lookup returns SessionUser → g.user is the SessionUser
- Cookie present, lookup returns None (expired/disabled) → g.user is None
- Cookie present, lookup raises exception → g.user is None (safe fallback)
- Idempotency guard: second call within same request context is a no-op
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask, g

from src.auth.load_user import load_session_user
from src.auth.sessions import SessionUser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Minimal Flask app with load_session_user wired as before_request hook."""
    _app = Flask(__name__)
    _app.config["TESTING"] = True
    _app.before_request(load_session_user)

    @_app.route("/whoami")
    def whoami():
        user = g.get("user")
        if user is None:
            return "anonymous", 200
        return f"{user.email}:{user.role}", 200

    return _app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_SESSION_USER = SessionUser(
    id="uid-alice",
    email="alice@example.com",
    display_name="Alice",
    role="reviewer",
    account_status="active",
)

_COOKIE_NAME = "auth_session_dev"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadSessionUserHook:
    def test_no_cookie_sets_user_none(self, client, monkeypatch):
        """Requests without a session cookie get g.user = None."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session") as mock_lookup:
            response = client.get("/whoami")

        assert response.status_code == 200
        assert response.data == b"anonymous"
        mock_lookup.assert_not_called()

    def test_valid_cookie_sets_session_user(self, client, monkeypatch):
        """Valid session cookie → g.user is the resolved SessionUser."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session", return_value=_SESSION_USER):
            client.set_cookie(_COOKIE_NAME, "valid-session-id")
            response = client.get("/whoami")

        assert response.status_code == 200
        assert b"alice@example.com:reviewer" in response.data

    def test_expired_session_sets_user_none(self, client, monkeypatch):
        """Expired/invalid session → lookup returns None → g.user = None."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session", return_value=None):
            client.set_cookie(_COOKIE_NAME, "expired-session-id")
            response = client.get("/whoami")

        assert response.status_code == 200
        assert response.data == b"anonymous"

    def test_lookup_exception_falls_back_to_none(self, client, monkeypatch):
        """If lookup_session raises, g.user is set to None (no 500 error)."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session", side_effect=RuntimeError("DB exploded")):
            client.set_cookie(_COOKIE_NAME, "some-session-id")
            response = client.get("/whoami")

        assert response.status_code == 200
        assert response.data == b"anonymous"

    def test_idempotency_guard_prevents_double_lookup(self, app, monkeypatch):
        """Second call to load_session_user within same request is a no-op."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        call_count = 0

        def _counting_lookup(sid):
            nonlocal call_count
            call_count += 1
            return _SESSION_USER

        with app.test_request_context(
            "/whoami",
            headers={"Cookie": f"{_COOKIE_NAME}=some-session"},
        ):
            with patch("src.auth.load_user.lookup_session", side_effect=_counting_lookup):
                load_session_user()
                load_session_user()  # second call should be a no-op

        assert call_count == 1

    def test_empty_cookie_value_sets_user_none(self, client, monkeypatch):
        """Cookie present but empty value → g.user = None, no lookup."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session") as mock_lookup:
            client.set_cookie(_COOKIE_NAME, "")
            response = client.get("/whoami")

        assert response.status_code == 200
        assert response.data == b"anonymous"
        mock_lookup.assert_not_called()

    def test_g_user_is_none_type_for_anonymous(self, app, monkeypatch):
        """Confirm g.user is explicitly None (not missing) for anonymous requests."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        captured = {}

        @app.route("/capture")
        def capture():
            captured["has_user"] = "user" in g
            captured["user_value"] = g.get("user")
            return "ok"

        with app.test_client() as c:
            c.get("/capture")

        assert captured["has_user"] is True
        assert captured["user_value"] is None
