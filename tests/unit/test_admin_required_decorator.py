"""
Unit tests for ``src.auth.admin.admin_required`` decorator.

Verification:
  - Anonymous (no g.user) → 403
  - Reviewer role → 403
  - Viewer role → 403
  - Admin role → 200 (delegate to wrapped function)
  - Feature-flag independence: auth_enforcement_enabled=False + reviewer → still 403
"""

from __future__ import annotations

import pytest
from flask import Flask, g, jsonify

from src.auth.admin import admin_required
from src.auth.sessions import SessionUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str) -> SessionUser:
    return SessionUser(
        id="00000000-0000-0000-0000-000000000099",
        email="testuser@example.com",
        display_name="Test User",
        role=role,
        account_status="active",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with one admin_required-protected endpoint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    @flask_app.route("/admin/secret")
    @admin_required
    def admin_endpoint():  # type: ignore[return]
        return jsonify({"ok": True}), 200

    return flask_app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdminRequired:
    def test_anonymous_returns_403(self, app: Flask) -> None:
        """No g.user (unauthenticated) → 403 with 'admin access required'."""
        with app.test_client() as client:
            resp = client.get("/admin/secret")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data is not None
        assert "admin access required" in data.get("error", "")

    def test_reviewer_role_returns_403(self, app: Flask) -> None:
        """Authenticated reviewer → 403 (not admin)."""
        reviewer = _make_user("reviewer")

        @app.before_request
        def inject_reviewer():
            g.user = reviewer

        with app.test_client() as client:
            resp = client.get("/admin/secret")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data is not None
        assert "admin access required" in data.get("error", "")

    def test_viewer_role_returns_403(self, app: Flask) -> None:
        """Authenticated viewer → 403 (not admin)."""
        viewer = _make_user("viewer")

        @app.before_request
        def inject_viewer():
            g.user = viewer

        with app.test_client() as client:
            resp = client.get("/admin/secret")
        assert resp.status_code == 403

    def test_admin_role_returns_200(self, app: Flask) -> None:
        """Authenticated admin → 200 (delegated to wrapped function)."""
        admin = _make_user("admin")

        @app.before_request
        def inject_admin():
            g.user = admin

        with app.test_client() as client:
            resp = client.get("/admin/secret")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_flag_off_still_blocks_reviewer(self, app: Flask, monkeypatch) -> None:
        """Feature-flag independence: auth_enforcement_enabled=False + reviewer → 403.

        admin_required is hard-gated and does NOT consult the feature flag.
        The existing require() decorator is a no-op when the flag is False;
        admin_required must NOT share that behavior.
        """
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: False)
        reviewer = _make_user("reviewer")

        @app.before_request
        def inject_reviewer():
            g.user = reviewer

        with app.test_client() as client:
            resp = client.get("/admin/secret")
        # Must be 403 — flag-off must NOT grant a pass-through here.
        assert resp.status_code == 403

    def test_flag_off_still_blocks_anonymous(self, app: Flask, monkeypatch) -> None:
        """Feature-flag independence: auth_enforcement_enabled=False + no user → 403."""
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: False)

        with app.test_client() as client:
            resp = client.get("/admin/secret")
        assert resp.status_code == 403

    def test_flag_off_still_admits_admin(self, app: Flask, monkeypatch) -> None:
        """Feature-flag independence: auth_enforcement_enabled=False + admin → 200."""
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: False)
        admin = _make_user("admin")

        @app.before_request
        def inject_admin():
            g.user = admin

        with app.test_client() as client:
            resp = client.get("/admin/secret")
        assert resp.status_code == 200

    def test_functools_wraps_preserves_name(self) -> None:
        """admin_required preserves the wrapped function's __name__ via functools.wraps."""

        def my_view():  # type: ignore[return]
            return jsonify(ok=True), 200

        wrapped = admin_required(my_view)
        assert wrapped.__name__ == "my_view"
