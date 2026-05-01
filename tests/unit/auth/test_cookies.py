"""
Unit tests for src/auth/cookies.py.

Tests use a minimal Flask test app so that Flask's Response object is
available without a full application context. No DB calls are made.

Coverage:
- _cookie_name: default, custom env var
- _is_production: APP_ENV=production vs anything else
- set_session_cookie: sets correct name, value, httponly, samesite
- set_session_cookie: Secure=True in production, Secure=False in dev
- set_session_cookie: no max_age / expires (session-cookie behaviour)
- clear_session_cookie: empty value, max_age=0
- get_session_id_from_request: present cookie, absent cookie, empty value
"""

from __future__ import annotations

import pytest
from flask import Flask

from src.auth.cookies import (
    _cookie_name,
    _is_production,
    clear_session_cookie,
    get_session_id_from_request,
    set_session_cookie,
)

# ---------------------------------------------------------------------------
# Minimal Flask app fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a minimal Flask app for request/response testing."""
    _app = Flask(__name__)
    _app.config["TESTING"] = True
    return _app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# _cookie_name
# ---------------------------------------------------------------------------


class TestCookieName:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)
        assert _cookie_name() == "auth_session_dev"

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_COOKIE_NAME", "auth_session")
        assert _cookie_name() == "auth_session"


# ---------------------------------------------------------------------------
# _is_production
# ---------------------------------------------------------------------------


class TestIsProduction:
    def test_not_production_by_default(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        assert _is_production() is False

    def test_development_not_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        assert _is_production() is False

    def test_production_true(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        assert _is_production() is True

    def test_staging_not_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        assert _is_production() is False


# ---------------------------------------------------------------------------
# set_session_cookie
# ---------------------------------------------------------------------------


class TestSetSessionCookie:
    def test_sets_cookie_name_and_value(self, app, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            set_session_cookie(response, "test-session-id-123")

        cookie_header = response.headers.get("Set-Cookie", "")
        assert "auth_session_dev" in cookie_header
        assert "test-session-id-123" in cookie_header

    def test_httponly_always_set(self, app, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            set_session_cookie(response, "sid")

        cookie_header = response.headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie_header

    def test_samesite_lax_always_set(self, app, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            set_session_cookie(response, "sid")

        cookie_header = response.headers.get("Set-Cookie", "").lower()
        assert "samesite=lax" in cookie_header

    def test_secure_false_in_development(self, app, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            set_session_cookie(response, "sid")

        cookie_header = response.headers.get("Set-Cookie", "")
        # "Secure" should NOT appear when not in production
        assert "Secure" not in cookie_header

    def test_secure_true_in_production(self, app, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            set_session_cookie(response, "sid")

        cookie_header = response.headers.get("Set-Cookie", "")
        assert "Secure" in cookie_header

    def test_no_max_age_or_expires(self, app, monkeypatch):
        """Cookie must be a session cookie — no Max-Age or Expires attribute."""
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            set_session_cookie(response, "sid")

        cookie_header = response.headers.get("Set-Cookie", "").lower()
        assert "max-age" not in cookie_header
        assert "expires" not in cookie_header

    def test_custom_cookie_name(self, app, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_COOKIE_NAME", "my_session")
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            set_session_cookie(response, "sid-value")

        cookie_header = response.headers.get("Set-Cookie", "")
        assert "my_session" in cookie_header
        assert "sid-value" in cookie_header


# ---------------------------------------------------------------------------
# clear_session_cookie
# ---------------------------------------------------------------------------


class TestClearSessionCookie:
    def test_sets_empty_value(self, app, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            clear_session_cookie(response)

        cookie_header = response.headers.get("Set-Cookie", "")
        # Cookie name present with empty value
        assert "auth_session_dev=" in cookie_header

    def test_max_age_zero(self, app, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            clear_session_cookie(response)

        cookie_header = response.headers.get("Set-Cookie", "").lower()
        assert "max-age=0" in cookie_header

    def test_httponly_present(self, app, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)

        with app.test_request_context("/"):
            response = app.response_class(status=200)
            clear_session_cookie(response)

        cookie_header = response.headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie_header


# ---------------------------------------------------------------------------
# get_session_id_from_request
# ---------------------------------------------------------------------------


class TestGetSessionIdFromRequest:
    def test_returns_session_id_when_present(self, app, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with app.test_request_context("/", headers={"Cookie": "auth_session_dev=my-session-id"}):
            from flask import request

            result = get_session_id_from_request(request)

        assert result == "my-session-id"

    def test_returns_none_when_cookie_absent(self, app, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with app.test_request_context("/"):
            from flask import request

            result = get_session_id_from_request(request)

        assert result is None

    def test_returns_none_when_value_empty(self, app, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with app.test_request_context("/", headers={"Cookie": "auth_session_dev="}):
            from flask import request

            result = get_session_id_from_request(request)

        assert result is None

    def test_strips_whitespace(self, app, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_COOKIE_NAME", raising=False)

        with app.test_request_context("/", headers={"Cookie": "auth_session_dev=  sid-123  "}):
            from flask import request

            result = get_session_id_from_request(request)

        assert result == "sid-123"

    def test_custom_cookie_name(self, app, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_COOKIE_NAME", "custom_cookie")

        with app.test_request_context("/", headers={"Cookie": "custom_cookie=my-id"}):
            from flask import request

            result = get_session_id_from_request(request)

        assert result == "my-id"
