"""
Unit tests for src/auth/csrf.py — csrf_protect() before_request hook.

Tests exercise:
  - GET requests are exempt regardless of flag state.
  - /auth/ path prefix is exempt (even when flag on and cross-origin).
  - Same-origin POST (Sec-Fetch-Site: same-origin) passes when flag on.
  - Cross-origin POST (no Sec-Fetch-Site, cross-origin Origin) → 403 when flag on.
  - Flag off (row missing OR enabled=false) → cross-origin POST passes.

DB calls are mocked via unittest.mock.patch so no real database is required.
The flag cache is reset between tests to prevent state leakage.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.auth.csrf as csrf_module
from src.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_flag_cache():
    """Clear the module-level flag cache before each test."""
    csrf_module._FLAG_CACHE = None
    yield
    csrf_module._FLAG_CACHE = None


@pytest.fixture()
def app():
    """Minimal Flask test app with CSRF middleware registered."""
    from unittest.mock import patch as _patch

    # Patch is_enabled at the source so create_app() never calls get_db().
    # Patching src.web.app.get_db here would poison any blueprint that imports
    # get_db at module level (e.g. ingest.py line 55), permanently replacing
    # its bound reference with the test MagicMock for the rest of the session.
    with _patch("src.auth.feature_flags.is_enabled", return_value=False):
        return create_app(
            config_name="testing",
            config_override={
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "API_KEY_REQUIRED": False,
            },
        )


@pytest.fixture()
def client(app):
    return app.test_client()


def _mock_db_flag_enabled(rows: list[dict]) -> MagicMock:
    """Return a MagicMock db whose query() returns the given rows."""
    db = MagicMock()
    db.query.return_value = rows
    return db


# ---------------------------------------------------------------------------
# Helper: patch get_db to return a mock that emits specified flag rows.
# ---------------------------------------------------------------------------


def _patch_flag(rows: list[dict]):
    """Patch src.web.app.get_db (used by _read_enforcement_flag) to return mock.

    _read_enforcement_flag does `from src.web.app import get_db` inside the
    function body, so we patch at the source: src.web.app.get_db.
    """
    mock_db = _mock_db_flag_enabled(rows)
    return patch("src.web.app.get_db", return_value=mock_db)


# ---------------------------------------------------------------------------
# Tests: safe methods are always exempt
# ---------------------------------------------------------------------------


class TestSafeMethodsExempt:
    def test_get_passes_when_flag_off(self, client):
        with _patch_flag([]):  # flag missing → off
            resp = client.get(
                "/health",
                headers={"Origin": "https://evil.example.com"},
            )
        # /health returns 200 regardless of CSRF (GET is exempt)
        assert resp.status_code != 403

    def test_get_passes_when_flag_on(self, client):
        with _patch_flag([{"value": "true"}]):
            resp = client.get(
                "/health",
                headers={
                    "Origin": "https://evil.example.com",
                    "Sec-Fetch-Site": "cross-site",
                },
            )
        assert resp.status_code != 403

    def test_head_passes_when_flag_on(self, client):
        with _patch_flag([{"value": "true"}]):
            resp = client.head(
                "/health",
                headers={"Origin": "https://evil.example.com"},
            )
        assert resp.status_code != 403

    def test_options_passes_when_flag_on(self, client):
        with _patch_flag([{"value": "true"}]):
            resp = client.options(
                "/health",
                headers={"Origin": "https://evil.example.com"},
            )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Tests: /auth/ path prefix is always exempt
# ---------------------------------------------------------------------------


class TestAuthPathExempt:
    def test_auth_callback_post_exempt_when_flag_on_cross_origin(self, client):
        """POST /auth/callback must pass even when flag=on and cross-origin."""
        with _patch_flag([{"value": "true"}]):
            # No Sec-Fetch-Site, cross-origin Origin — would normally 403.
            resp = client.post(
                "/auth/callback",
                headers={"Origin": "https://evil.example.com"},
            )
        # /auth/callback doesn't exist (404) but CSRF must NOT produce 403.
        assert resp.status_code != 403

    def test_auth_login_post_exempt(self, client):
        with _patch_flag([{"value": "true"}]):
            resp = client.post(
                "/auth/login",
                headers={"Origin": "https://attacker.example.com"},
            )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Tests: flag on — same-origin passes, cross-origin blocked
# ---------------------------------------------------------------------------


class TestFlagOn:
    def test_same_origin_sec_fetch_site_passes(self, client):
        """Sec-Fetch-Site: same-origin → allowed when flag on."""
        with _patch_flag([{"value": "true"}]):
            resp = client.post(
                "/health",
                headers={"Sec-Fetch-Site": "same-origin"},
            )
        assert resp.status_code != 403

    def test_same_origin_via_origin_header_passes(self, client, app):
        """Origin header matching request.host → allowed when flag on."""
        with app.test_request_context():
            # Determine the host the test client uses
            host = "localhost"

        with _patch_flag([{"value": "true"}]):
            resp = client.post(
                "/health",
                headers={"Origin": f"http://{host}"},
            )
        assert resp.status_code != 403

    def test_cross_origin_post_blocked_when_flag_on(self, client):
        """Cross-origin POST with no Sec-Fetch-Site header → 403."""
        with _patch_flag([{"value": "true"}]):
            resp = client.post(
                "/health",
                headers={"Origin": "https://evil.example.com"},
            )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data is not None
        assert data.get("error") == "CSRF check failed"

    def test_cross_origin_with_cross_site_sec_fetch_blocked(self, client):
        """Sec-Fetch-Site: cross-site → 403 even when Origin matches nothing."""
        with _patch_flag([{"value": "true"}]):
            resp = client.post(
                "/health",
                headers={
                    "Origin": "https://attacker.example.com",
                    "Sec-Fetch-Site": "cross-site",
                },
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: flag off → cross-origin POST passes (no-op)
# ---------------------------------------------------------------------------


class TestFlagOff:
    def test_flag_row_missing_cross_origin_passes(self, client):
        """Row absent in feature_flags → middleware is no-op."""
        with _patch_flag([]):  # empty result → flag absent
            resp = client.post(
                "/health",
                headers={"Origin": "https://evil.example.com"},
            )
        assert resp.status_code != 403

    def test_flag_value_false_cross_origin_passes(self, client):
        """Row present with value='false' → middleware is no-op."""
        with _patch_flag([{"value": "false"}]):
            resp = client.post(
                "/health",
                headers={"Origin": "https://evil.example.com"},
            )
        assert resp.status_code != 403

    def test_db_error_defaults_to_flag_off(self, client):
        """DB read exception → flag defaults to False → cross-origin passes."""
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("connection refused")
        with patch("src.web.app.get_db", return_value=mock_db):
            resp = client.post(
                "/health",
                headers={"Origin": "https://evil.example.com"},
            )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Tests: flag cache behavior
# ---------------------------------------------------------------------------


class TestFlagCache:
    def test_flag_is_cached_within_ttl(self, client):
        """DB should not be queried a second time within the cache TTL."""
        mock_db = MagicMock()
        mock_db.query.return_value = []  # flag off

        with patch("src.web.app.get_db", return_value=mock_db):
            # First request — reads DB.
            client.post("/health", headers={"Origin": "https://evil.example.com"})
            # Second request — should use cache.
            client.post("/health", headers={"Origin": "https://evil.example.com"})

        # query() should have been called only once.
        assert mock_db.query.call_count == 1

    def test_cache_refreshed_after_ttl(self, client):
        """After TTL expires the DB is queried again."""
        import src.auth.csrf as _csrf

        mock_db = MagicMock()
        mock_db.query.return_value = []

        with patch("src.web.app.get_db", return_value=mock_db):
            # Prime cache.
            client.post("/health", headers={"Origin": "https://evil.example.com"})

        # Manually expire the cache.
        assert _csrf._FLAG_CACHE is not None
        value, _ = _csrf._FLAG_CACHE
        _csrf._FLAG_CACHE = (value, 0.0)  # set timestamp to epoch → expired

        with patch("src.web.app.get_db", return_value=mock_db):
            client.post("/health", headers={"Origin": "https://evil.example.com"})

        # query() should have been called a second time.
        assert mock_db.query.call_count == 2


# ---------------------------------------------------------------------------
# Tests: programmer errors propagate rather than silently defaulting to off
# ---------------------------------------------------------------------------


class TestProgrammerErrorPropagates:
    def test_runtime_error_propagates_from_flag_read(self, client):
        """RuntimeError during flag read re-raises instead of defaulting to False."""
        from unittest.mock import patch

        def boom():
            raise RuntimeError("Working outside of application context")

        with patch("src.web.app.get_db", boom):
            with pytest.raises(RuntimeError):
                client.post(
                    "/health",
                    headers={"Origin": "https://evil.example.com"},
                )
