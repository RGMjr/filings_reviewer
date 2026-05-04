"""
Unit tests for the flag-awareness of ``src.auth.middleware.require()``.

PR-C1 made the decorator a no-op when ``auth_enforcement_enabled`` is False
so applying decorators across the route surface is safe to merge before the
operator flips the flag. This file pins that behavior.
"""

from __future__ import annotations

import pytest
from flask import Flask, g, jsonify

from src.auth.middleware import require
from src.auth.permissions import DECISION_WRITE
from src.auth.sessions import SessionUser


def _make_user(role: str) -> SessionUser:
    return SessionUser(
        id="00000000-0000-0000-0000-000000000001",
        email="test@example.com",
        display_name="Test User",
        role=role,
        account_status="active",
    )


@pytest.fixture()
def app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    @flask_app.route("/protected")
    @require(DECISION_WRITE)
    def protected_endpoint():
        return jsonify(ok=True), 200

    return flask_app


class TestRequireFlagAware:
    def test_flag_off_passes_unauthenticated(self, app: Flask, monkeypatch) -> None:
        """When auth_enforcement_enabled=False, require() is a no-op even with no g.user."""
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: False)
        with app.test_client() as client:
            resp = client.get("/protected", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_flag_off_passes_viewer_lacking_permission(self, app: Flask, monkeypatch) -> None:
        """No-op decorator skips role check too — viewer lacks decision.write but flag-off lets it through."""
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: False)
        viewer = _make_user("viewer")

        @app.before_request
        def inject_user():
            g.user = viewer

        with app.test_client() as client:
            resp = client.get("/protected", headers={"Accept": "application/json"})
        assert resp.status_code == 200

    def test_flag_on_blocks_unauthenticated(self, app: Flask, monkeypatch) -> None:
        """When auth_enforcement_enabled=True, require() enforces — no g.user → 401."""
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: True)
        with app.test_client() as client:
            resp = client.get("/protected", headers={"Accept": "application/json"})
        assert resp.status_code == 401

    def test_flag_on_blocks_viewer(self, app: Flask, monkeypatch) -> None:
        """When flag-on, viewer lacks decision.write → 403."""
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: True)
        viewer = _make_user("viewer")

        @app.before_request
        def inject_user():
            g.user = viewer

        with app.test_client() as client:
            resp = client.get("/protected", headers={"Accept": "application/json"})
        assert resp.status_code == 403

    def test_flag_on_admits_reviewer(self, app: Flask, monkeypatch) -> None:
        """When flag-on, reviewer holds decision.write → 200."""
        monkeypatch.setattr("src.auth.feature_flags.is_enabled", lambda key: True)
        reviewer = _make_user("reviewer")

        @app.before_request
        def inject_user():
            g.user = reviewer

        with app.test_client() as client:
            resp = client.get("/protected", headers={"Accept": "application/json"})
        assert resp.status_code == 200

    def test_flag_lookup_failure_defaults_to_no_op(self, app: Flask, monkeypatch) -> None:
        """A DB outage on flag lookup → fail-open as no-op (existing behavior pre-flip)."""

        def boom(key: str) -> bool:
            raise RuntimeError("DB down")

        monkeypatch.setattr("src.auth.feature_flags.is_enabled", boom)
        with app.test_client() as client:
            resp = client.get("/protected", headers={"Accept": "application/json"})
        # No g.user, but flag lookup failed → no-op pass-through.
        assert resp.status_code == 200
