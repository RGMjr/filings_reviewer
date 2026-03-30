"""
Unit tests for API authentication.

Tests the API key authentication mechanism for /api/* routes.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


@pytest.fixture
def app_with_auth():
    """Create Flask app with authentication enabled."""
    app = create_app(
        config_name="testing",
        config_override={
            "API_KEY": "test-secret-key-12345",
            "API_KEY_REQUIRED": True,
        },
    )
    return app


@pytest.fixture
def client_with_auth(app_with_auth):
    """Test client for auth-enabled app."""
    with patch("src.web.routes.api.get_db", return_value=MagicMock()):
        yield app_with_auth.test_client()


class TestAPIAuthentication:
    """Test API key authentication."""

    def test_missing_api_key_returns_401(self, client_with_auth):
        """Request without API key should return 401."""
        response = client_with_auth.post(
            "/api/decisions",
            json={"candidate_id": 1, "decision": "accept"},
        )
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "API key required" in data["message"]

    def test_invalid_api_key_returns_401(self, client_with_auth):
        """Request with wrong API key should return 401."""
        response = client_with_auth.post(
            "/api/decisions",
            json={"candidate_id": 1, "decision": "accept"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Invalid API key" in data["message"]

    def test_valid_api_key_in_header_passes(self, client_with_auth):
        """Request with valid API key in header should pass auth."""
        # Note: This will fail validation (no candidate_id), but should get past auth
        response = client_with_auth.post(
            "/api/decisions",
            json={},  # Invalid body, but tests auth passes
            headers={"X-API-Key": "test-secret-key-12345"},
        )
        # Should get 400 (validation error), not 401 (auth error)
        assert response.status_code == 400

    def test_valid_api_key_in_query_param_passes(self, client_with_auth):
        """Request with valid API key in query param should pass auth."""
        response = client_with_auth.post(
            "/api/decisions?api_key=test-secret-key-12345",
            json={},
        )
        # Should get 400 (validation error), not 401 (auth error)
        assert response.status_code == 400

    def test_image_api_requires_auth(self, client_with_auth):
        """Image API routes should also require authentication."""
        response = client_with_auth.post(
            "/api/image-decisions",
            json={"image_candidate_id": 1, "decision": "relevant"},
        )
        assert response.status_code == 401


class TestAuthDisabled:
    """Test that auth can be disabled for development."""

    def test_auth_disabled_allows_requests(self, client):
        """When API_KEY_REQUIRED is False, requests should pass without key."""
        # This uses the default testing config which has API_KEY_REQUIRED=False
        response = client.post(
            "/api/decisions",
            json={},  # Invalid body
        )
        # Should get 400 (validation error), not 401 (auth error)
        assert response.status_code == 400


@pytest.fixture
def client():
    """Create test client with auth disabled (default testing config)."""
    app = create_app(config_name="testing")
    with patch("src.web.routes.api.get_db", return_value=MagicMock()):
        yield app.test_client()
