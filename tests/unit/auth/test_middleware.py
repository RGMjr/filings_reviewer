"""
Unit tests for src.auth.middleware.require() — Flask route decorator.

Verification checklist items from PR-A2 spec:
  - A no-op g.user=None request to a require()-decorated route returns 401
    (JSON or HTML depending on Accept header).
  - An authenticated user without permission returns 403.
  - An authenticated user with the required permission reaches the handler (200).
"""

from __future__ import annotations

import pytest
from flask import Flask, g, jsonify

from src.auth.middleware import require
from src.auth.permissions import DECISION_UNDO_ANY, DECISION_WRITE
from src.auth.sessions import SessionUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str) -> SessionUser:
    return SessionUser(
        id="00000000-0000-0000-0000-000000000001",
        email="test@example.com",
        display_name="Test User",
        role=role,
        account_status="active",
    )


# ---------------------------------------------------------------------------
# require() decorator — minimal Flask test app
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_protected_route() -> Flask:
    """Minimal Flask app with one require()-protected endpoint."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/protected")
    @require(DECISION_WRITE)
    def protected_endpoint():  # type: ignore[return]
        return jsonify(ok=True), 200

    return app


class TestRequireDecorator:
    """Test the require() middleware under various g.user states."""

    def test_unauthenticated_json_returns_401(self, app_with_protected_route: Flask) -> None:
        """g.user=None + Accept:json -> 401 JSON."""
        with app_with_protected_route.test_client() as client:
            resp = client.get(
                "/protected",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 401
            data = resp.get_json()
            assert data is not None
            assert "error" in data

    def test_unauthenticated_html_returns_401_or_redirect(
        self, app_with_protected_route: Flask
    ) -> None:
        """g.user=None + Accept:text/html -> 401 (login redirect or 401 JSON fallback).

        The login blueprint is not registered in this minimal test app so
        url_for('auth.login') raises BuildError; the decorator falls back to 401 JSON.
        """
        with app_with_protected_route.test_client() as client:
            resp = client.get(
                "/protected",
                headers={"Accept": "text/html"},
            )
            # Either a redirect to login (302) or 401 fallback.
            assert resp.status_code in {302, 401}

    def test_authorized_user_passes(self, app_with_protected_route: Flask) -> None:
        """A reviewer (who has decision.write) reaches the handler."""
        reviewer = _make_user("reviewer")

        @app_with_protected_route.before_request
        def inject_user():  # type: ignore[return]
            g.user = reviewer

        with app_with_protected_route.test_client() as client:
            resp = client.get(
                "/protected",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 200

    def test_viewer_lacks_decision_write_returns_403(self) -> None:
        """viewer role lacks decision.write -> 403."""
        viewer = _make_user("viewer")

        app2 = Flask(__name__ + "_viewer")
        app2.config["TESTING"] = True

        @app2.before_request
        def inject():  # type: ignore[return]
            g.user = viewer

        @app2.route("/protected")
        @require(DECISION_WRITE)
        def protected():  # type: ignore[return]
            return jsonify(ok=True), 200

        with app2.test_client() as client:
            resp = client.get(
                "/protected",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 403
            data = resp.get_json()
            assert data is not None
            assert "error" in data

    def test_reviewer_lacks_decision_undo_any_returns_403(self) -> None:
        """reviewer lacks decision.undo.any -> 403 on that endpoint."""
        reviewer = _make_user("reviewer")

        app3 = Flask(__name__ + "_reviewer_undo_any")
        app3.config["TESTING"] = True

        @app3.before_request
        def inject():  # type: ignore[return]
            g.user = reviewer

        @app3.route("/admin-only")
        @require(DECISION_UNDO_ANY)
        def admin_only():  # type: ignore[return]
            return jsonify(ok=True), 200

        with app3.test_client() as client:
            resp = client.get(
                "/admin-only",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 403

    def test_admin_has_decision_undo_any(self) -> None:
        """admin role reaches a decision.undo.any endpoint."""
        admin = _make_user("admin")

        app4 = Flask(__name__ + "_admin_undo_any")
        app4.config["TESTING"] = True

        @app4.before_request
        def inject():  # type: ignore[return]
            g.user = admin

        @app4.route("/admin-only")
        @require(DECISION_UNDO_ANY)
        def admin_only():  # type: ignore[return]
            return jsonify(ok=True), 200

        with app4.test_client() as client:
            resp = client.get(
                "/admin-only",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 200
