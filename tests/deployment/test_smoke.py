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

    Post-PR-C1: the blueprint-wide ``register_api_auth`` gate on /api/v2/* is
    gone. Routes are gated by per-route ``@require(<perm>)`` decorators that
    are flag-aware — no-op when ``auth_enforcement_enabled=False`` (default
    pre-flip). These tests originally asserted that missing/invalid API keys
    return 401, which only holds once the operator flips the flag via the
    Stage-C runbook (``docs/operations/auth-stage-c-runbook.md``). Re-enable
    the assertions after the flip and update them for the new contract
    (missing session → 401; valid session → 200; etc.).
    """

    def test_api_rejects_missing_key(self, base_url: str, is_live: bool) -> None:
        pytest.skip(
            "Pre-flag-flip transition: /api/v2/* require() decorators are no-op "
            "when auth_enforcement_enabled=False. Re-enable post Stage-C flip."
        )

    def test_api_rejects_invalid_key(self, base_url: str, is_live: bool) -> None:
        pytest.skip(
            "Pre-flag-flip transition: /api/v2/* require() decorators are no-op "
            "when auth_enforcement_enabled=False. Re-enable post Stage-C flip."
        )

    def test_api_accepts_valid_key(self, base_url: str, api_key: str, is_live: bool) -> None:
        if not is_live:
            pytest.skip("Auth enforcement tests only run against live deployment")
        # POST /api/v2/decisions with a valid key should get past auth (400/422 for bad
        # payload is acceptable — what we're testing is that auth passes, not business logic)
        r = requests.post(
            f"{base_url}/api/v2/decisions",
            json={},
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        assert r.status_code != 401, f"Expected auth to pass with valid key, got {r.status_code}"
