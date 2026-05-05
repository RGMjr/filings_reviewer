"""
Unit tests for the Stage-C API-key bridge (gh-483).

``load_api_key_user`` runs as a second ``before_request`` hook after
``load_session_user``.  When the session-cookie path did not authenticate the
request and the caller supplied a valid API key, it populates
``flask.g.user`` with a synthetic admin ``SessionUser`` so per-route
``@require(<perm>)`` decorators pass once enforcement is on.

These tests mock ``lookup_session`` at the boundary so no DB connection is
needed, and run the actual Flask request lifecycle through a minimal app
that wires both hooks in production order.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask, g

from src.auth.load_user import load_api_key_user, load_session_user
from src.auth.service_account import SERVICE_ACCOUNT_ID
from src.auth.sessions import SessionUser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_API_KEY = "test-secret-key-xyz"
_COOKIE_NAME = "auth_session_dev"

_SESSION_USER = SessionUser(
    id="uid-alice",
    email="alice@example.com",
    display_name="Alice",
    role="reviewer",
    account_status="active",
)


@pytest.fixture()
def app():
    """Flask app with both before_request hooks wired in production order.

    ``load_session_user`` first (so a real session always wins), then
    ``load_api_key_user``.
    """
    _app = Flask(__name__)
    _app.config["TESTING"] = True
    _app.config["API_KEY_REQUIRED"] = True
    _app.config["API_KEY"] = _API_KEY
    _app.before_request(load_session_user)
    _app.before_request(load_api_key_user)

    @_app.route("/whoami")
    def whoami():
        user = g.get("user")
        if user is None:
            return "anonymous", 200
        return f"{user.email}:{user.role}:{user.id}", 200

    return _app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadApiKeyUserHook:
    def test_valid_authorization_header_sets_service_account(self, client, monkeypatch):
        """No session, valid Authorization: ApiKey → service-account admin user."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session") as mock_lookup:
            response = client.get(
                "/whoami",
                headers={"Authorization": f"ApiKey {_API_KEY}"},
            )

        assert response.status_code == 200
        assert b"api-key@service.local:admin" in response.data
        assert SERVICE_ACCOUNT_ID.encode() in response.data
        mock_lookup.assert_not_called()

    def test_valid_x_api_key_header_sets_service_account(self, client, monkeypatch):
        """X-API-Key header is also accepted (legacy header shape)."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session"):
            response = client.get(
                "/whoami",
                headers={"X-API-Key": _API_KEY},
            )

        assert response.status_code == 200
        assert b"api-key@service.local:admin" in response.data

    def test_invalid_key_leaves_user_anonymous(self, client, monkeypatch):
        """Invalid API key → g.user stays None (downstream @require will 401)."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session"):
            response = client.get(
                "/whoami",
                headers={"Authorization": "ApiKey not-the-key"},
            )

        assert response.status_code == 200
        assert response.data == b"anonymous"

    def test_no_header_leaves_user_anonymous(self, client, monkeypatch):
        """No API key, no session → g.user None."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session"):
            response = client.get("/whoami")

        assert response.status_code == 200
        assert response.data == b"anonymous"

    def test_session_user_wins_over_api_key(self, client, monkeypatch):
        """Both session cookie AND valid API key present → session wins."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session", return_value=_SESSION_USER):
            client.set_cookie(_COOKIE_NAME, "valid-session-id")
            response = client.get(
                "/whoami",
                headers={"Authorization": f"ApiKey {_API_KEY}"},
            )

        assert response.status_code == 200
        # Real session user (alice, reviewer) wins over the service account (admin).
        assert b"alice@example.com:reviewer" in response.data
        assert b"api-key@service.local" not in response.data

    def test_misconfigured_api_key_leaves_user_anonymous(self, app, monkeypatch):
        """API_KEY_REQUIRED=True but API_KEY unset → fail closed (g.user None)."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)
        app.config["API_KEY"] = ""

        client = app.test_client()
        with patch("src.auth.load_user.lookup_session"):
            response = client.get(
                "/whoami",
                headers={"Authorization": f"ApiKey {_API_KEY}"},
            )

        assert response.status_code == 200
        assert response.data == b"anonymous"

    def test_api_key_required_false_disables_bridge(self, app, monkeypatch):
        """API_KEY_REQUIRED=False → bridge is a no-op even with a valid key."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)
        app.config["API_KEY_REQUIRED"] = False

        client = app.test_client()
        with patch("src.auth.load_user.lookup_session"):
            response = client.get(
                "/whoami",
                headers={"Authorization": f"ApiKey {_API_KEY}"},
            )

        assert response.status_code == 200
        assert response.data == b"anonymous"

    def test_query_param_api_key_works(self, client, monkeypatch):
        """?api_key=<key> query param is also accepted."""
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with patch("src.auth.load_user.lookup_session"):
            response = client.get(f"/whoami?api_key={_API_KEY}")

        assert response.status_code == 200
        assert b"api-key@service.local:admin" in response.data
