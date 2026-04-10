"""HTTP smoke tests for deployment validation.

These tests run against either a local Docker container (default) or a live
deployment (set SMOKE_TEST_BASE_URL env var). They validate that core
endpoints are reachable and behave correctly.
"""

import pytest
import requests

pytestmark = pytest.mark.deployment


class TestHealthEndpoint:
    def test_health_returns_200(self, base_url: str) -> None:
        r = requests.get(f"{base_url}/health", timeout=10)
        assert r.status_code == 200

    def test_health_json_structure(self, base_url: str) -> None:
        r = requests.get(f"{base_url}/health", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert "pool_stats" in data

    def test_health_no_auth_required(self, base_url: str) -> None:
        """Health endpoint must not require authentication."""
        r = requests.get(f"{base_url}/health", timeout=10)
        assert r.status_code == 200


class TestPublicPages:
    def test_filing_list_loads(self, base_url: str) -> None:
        r = requests.get(f"{base_url}/", timeout=10)
        assert r.status_code == 200

    def test_v2_review_page_loads(self, base_url: str) -> None:
        r = requests.get(f"{base_url}/v2/review/filings", timeout=10)
        assert r.status_code == 200


class TestApiAuth:
    """Verify API authentication is enforced in production mode.

    Skipped against local containers because same-origin detection and
    APP_ENV behavior may differ. Against a live deployment, APP_ENV=production
    ensures auth is always enforced.
    """

    def test_api_rejects_missing_key(self, base_url: str, is_live: bool) -> None:
        if not is_live:
            pytest.skip("Auth enforcement tests only run against live deployment")
        r = requests.post(
            f"{base_url}/api/decisions",
            json={},
            timeout=10,
        )
        assert r.status_code == 401, (
            f"Expected 401 without API key, got {r.status_code}"
        )

    def test_api_rejects_invalid_key(self, base_url: str, is_live: bool) -> None:
        if not is_live:
            pytest.skip("Auth enforcement tests only run against live deployment")
        r = requests.post(
            f"{base_url}/api/decisions",
            json={},
            headers={"X-API-Key": "definitely-wrong-key-value"},
            timeout=10,
        )
        assert r.status_code == 401, (
            f"Expected 401 with invalid API key, got {r.status_code}"
        )

    def test_api_accepts_valid_key(self, base_url: str, api_key: str, is_live: bool) -> None:
        if not is_live:
            pytest.skip("Auth enforcement tests only run against live deployment")
        # POST /api/decisions with a valid key should get past auth (400/422 for bad
        # payload is acceptable — what we're testing is that auth passes, not business logic)
        r = requests.post(
            f"{base_url}/api/decisions",
            json={},
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        assert r.status_code != 401, (
            f"Expected auth to pass with valid key, got {r.status_code}"
        )
