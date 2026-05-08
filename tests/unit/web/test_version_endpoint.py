"""Unit tests for the /version endpoint registered in src/web/app.py."""

from __future__ import annotations

import json

import pytest

from src.web.app import create_app


@pytest.fixture()
def client():
    """Flask test client for a testing-config app."""
    app = create_app("testing")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestVersionEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/version")
        assert resp.status_code == 200

    def test_content_type_is_json(self, client):
        resp = client.get("/version")
        assert "application/json" in resp.content_type

    def test_sha_present_in_env(self, client, monkeypatch):
        """When RENDER_GIT_COMMIT is set the endpoint returns its value."""
        monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234def5678")
        resp = client.get("/version")
        body = json.loads(resp.data)
        assert body["git_sha"] == "abc1234def5678"

    def test_sha_absent_returns_unknown(self, client, monkeypatch):
        """When RENDER_GIT_COMMIT is absent the endpoint returns 'unknown'."""
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
        resp = client.get("/version")
        body = json.loads(resp.data)
        assert body["git_sha"] == "unknown"

    def test_no_auth_required(self, monkeypatch):
        """The endpoint must be reachable without an API key."""
        # Use a production-like config with API_KEY_REQUIRED=True to verify
        # the endpoint is exempt from auth gating.
        monkeypatch.setenv("RENDER_GIT_COMMIT", "deadbeef")
        app = create_app(
            "testing",
            config_override={"API_KEY_REQUIRED": True, "API_KEY": "secret"},
        )
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/version")
        # Should succeed without any Authorization header
        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body["git_sha"] == "deadbeef"
