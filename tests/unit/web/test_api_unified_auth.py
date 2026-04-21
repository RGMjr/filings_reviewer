"""
Unit tests for blueprint-wide auth guard on api_unified_bp.

`register_api_auth(api_unified_bp)` installs a before_request hook that calls
`_verify_api_key()` for every route on /api/v2/*.  These tests exercise the
auth path coverage that was missing (KNOWN_ISSUES #50), symmetric with
TestImageCropAuth in test_image_crop.py.

Chosen endpoint: DELETE /api/v2/decisions/<decision_id>

Rationale: it is a simple route that accepts a string path parameter and
returns 404 when the decision does not exist.  Because auth fires before the
route handler (via before_request), and we mock `get_db` to return a stub that
reports "not found", the test is entirely focused on auth-path behaviour with
no real DB state required.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db():
    db = MagicMock()
    # Returning None simulates "decision not found" → 404 from the handler.
    db.delete_v2_review_decision.return_value = None
    # insert_audit_log must not raise so after_request doesn't error.
    db.insert_audit_log.return_value = None
    return db


# Path of a simple, predictably-behaved endpoint.  Auth fires before the
# handler, so the exact path matters only for routing — any valid route works.
_ENDPOINT = "/api/v2/decisions/nonexistent-decision-id"


# ---------------------------------------------------------------------------
# TestApiUnifiedAuth
# ---------------------------------------------------------------------------


class TestApiUnifiedAuth:
    @pytest.fixture()
    def authed_app(self):
        return create_app(
            config_name="testing",
            config_override={
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "API_KEY_REQUIRED": True,
                "API_KEY": "test-key",
            },
        )

    @pytest.fixture()
    def authed_client(self, authed_app):
        return authed_app.test_client()

    # ------------------------------------------------------------------
    # 401 cases — auth is rejected before the handler runs
    # ------------------------------------------------------------------

    def test_missing_api_key_returns_401(self, authed_client, mock_db):
        """No X-API-Key header, no query arg, no same-origin markers → 401."""
        with patch("src.web.routes.api_unified.get_db", return_value=mock_db):
            resp = authed_client.delete(_ENDPOINT)
        assert resp.status_code == 401
        mock_db.delete_v2_review_decision.assert_not_called()

    def test_wrong_api_key_header_returns_401(self, authed_client, mock_db):
        with patch("src.web.routes.api_unified.get_db", return_value=mock_db):
            resp = authed_client.delete(
                _ENDPOINT,
                headers={"X-API-Key": "wrong-key"},
            )
        assert resp.status_code == 401
        mock_db.delete_v2_review_decision.assert_not_called()

    # ------------------------------------------------------------------
    # Accepted cases — auth passes, handler runs and returns 404 (no DB row)
    # ------------------------------------------------------------------

    def test_correct_api_key_header_passes_auth(self, authed_client, mock_db):
        """Correct X-API-Key header → auth passes; handler returns 404 (no row)."""
        with patch("src.web.routes.api_unified.get_db", return_value=mock_db):
            resp = authed_client.delete(
                _ENDPOINT,
                headers={"X-API-Key": "test-key"},
            )
        # 404 means auth passed and the handler ran (no matching DB row).
        assert resp.status_code == 404
        mock_db.delete_v2_review_decision.assert_called_once()

    def test_correct_api_key_query_arg_passes_auth(self, authed_client, mock_db):
        """Correct ?api_key= query param → same result as header."""
        with patch("src.web.routes.api_unified.get_db", return_value=mock_db):
            resp = authed_client.delete(_ENDPOINT + "?api_key=test-key")
        assert resp.status_code == 404
        mock_db.delete_v2_review_decision.assert_called_once()

    def test_same_origin_referer_bypass(self, authed_client, mock_db):
        """Referer matching host_url bypasses auth (same-origin browser navigation)."""
        with patch("src.web.routes.api_unified.get_db", return_value=mock_db):
            resp = authed_client.delete(
                _ENDPOINT,
                headers={"Referer": "http://localhost/v2/review/filings"},
            )
        assert resp.status_code == 404
        mock_db.delete_v2_review_decision.assert_called_once()

    # ------------------------------------------------------------------
    # 500 misconfiguration case
    # ------------------------------------------------------------------

    def test_api_key_required_but_unset_returns_500(self, mock_db):
        """API_KEY_REQUIRED=True but API_KEY=None is a server misconfiguration → 500."""
        app = create_app(
            config_name="testing",
            config_override={
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "API_KEY_REQUIRED": True,
                "API_KEY": None,
            },
        )
        client = app.test_client()
        with patch("src.web.routes.api_unified.get_db", return_value=mock_db):
            resp = client.delete(
                _ENDPOINT,
                headers={"X-API-Key": "anything"},
            )
        assert resp.status_code == 500
        mock_db.delete_v2_review_decision.assert_not_called()
