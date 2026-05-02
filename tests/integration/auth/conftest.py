"""
Shared fixtures for tests under ``tests/integration/auth/``.

Provides:
  - ``auth_truncate``: a helper that truncates the auth tables in a test DB.
    NOT a fixture — a callable so each test can decide when to truncate
    (the test_seed_scripts.py file already defines its own ``auth_db``
    fixture so we don't shadow it here).
  - ``oauth_app``: a Flask test app with the auth blueprint registered
    (the ``google_login_enabled`` flag is monkeypatched on for the duration
    of the fixture).
  - ``oauth_client``: a test client built from ``oauth_app``.
  - ``stub_google_oauth``: monkeypatch fakes for the Google token exchange
    and ID-token validation so tests don't make real network calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.auth.oidc_validate import OidcValidationError

# ---------------------------------------------------------------------------
# DB helpers (function — not a fixture, to avoid colliding with the per-file
# ``auth_db`` fixture in test_seed_scripts.py)
# ---------------------------------------------------------------------------


def _truncate_auth_tables(adapter) -> None:
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


@pytest.fixture
def auth_db_clean(test_db_adapter):
    """Test DB adapter with auth tables truncated before/after each test."""
    _truncate_auth_tables(test_db_adapter)
    yield test_db_adapter
    _truncate_auth_tables(test_db_adapter)


# ---------------------------------------------------------------------------
# Flask app + client with the auth blueprint registered
# ---------------------------------------------------------------------------


@pytest.fixture
def oauth_app(monkeypatch, test_db_adapter):
    """Construct a Flask app with the auth blueprint registered.

    Monkeypatches:
      - ``src.auth.feature_flags.is_enabled`` → True for ``google_login_enabled``.
      - ``GOOGLE_OAUTH_*`` env vars to dummy values.
      - ``DATABASE_URL`` / ``TEST_DATABASE_URL`` so the app's DB pool reaches
        the same test DB the test fixtures already populated.

    The flag patch must apply before ``create_app`` runs so the conditional
    blueprint registration sees the True value.
    """
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost/auth/callback")
    monkeypatch.setenv("APP_ENV", "testing")
    # ``src/auth/sessions.py`` reads ``os.environ['DATABASE_URL']`` directly
    # (it doesn't go through ``app.config``), so point it at the test DB
    # before ``create_app`` runs to keep auth_users / auth_sessions writes
    # in the same database.
    monkeypatch.setenv("DATABASE_URL", test_db_adapter.connection_string)

    # Force the conditional blueprint registration to fire.
    from src.auth import feature_flags

    feature_flags._clear_cache_for_tests()
    monkeypatch.setattr(
        "src.auth.feature_flags.is_enabled",
        lambda key: key == "google_login_enabled",
    )

    from src.web.app import create_app

    app = create_app(
        "testing",
        config_override={
            "DATABASE_URL": test_db_adapter.connection_string,
            "TESTING": True,
            "DB_POOL_ENABLED": False,
        },
    )
    return app


@pytest.fixture
def oauth_client(oauth_app):
    return oauth_app.test_client()


# ---------------------------------------------------------------------------
# Google response stubs
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_google_oauth(monkeypatch):
    """Return a builder that programs token exchange + ID token outcomes.

    Each test calls ``stub_google_oauth(claims=..., raise_validate=...)``
    to install patches. The token-exchange side always returns a fake
    ``{"id_token": "fake.jwt.payload"}``; the validation side returns
    ``claims`` (or raises ``raise_validate``).
    """

    def _install(
        *,
        claims: dict[str, Any] | None = None,
        raise_validate: Exception | None = None,
        raise_exchange: Exception | None = None,
    ):
        if raise_exchange is not None:

            def fake_exchange(**kwargs):
                raise raise_exchange

        else:

            def fake_exchange(**kwargs):
                return {"id_token": "fake.jwt.payload"}

        def fake_validate(id_token_str, *, client_id, expected_nonce):
            if raise_validate is not None:
                raise raise_validate
            assert claims is not None, "test must supply claims when not raising"
            return claims

        monkeypatch.setattr("src.web.routes.auth.exchange_code_for_tokens", fake_exchange)
        monkeypatch.setattr("src.web.routes.auth.validate_id_token", fake_validate)

    return _install


@pytest.fixture
def good_claims():
    """A minimal valid ID-token claims dict for happy-path tests."""
    return {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "sub": "google-sub-12345",
        "email": "alice@example.com",
        "email_verified": True,
        "nonce": "stash-me-test-nonce",
        "name": "Alice Example",
    }


# Re-export OidcValidationError for convenience in test files.
__all__ = ["OidcValidationError"]
