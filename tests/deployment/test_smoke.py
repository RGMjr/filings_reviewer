"""HTTP smoke tests for deployment validation.

These tests run against either a local Docker container (default) or a live
deployment (set SMOKE_TEST_BASE_URL env var). They validate that core
endpoints are reachable and behave correctly.
"""

from urllib.parse import urlparse

import pytest
import requests

pytestmark = pytest.mark.deployment


def _same_origin_headers(base_url: str) -> dict[str, str]:
    """Return an Origin header matching base_url's scheme+host.

    Required for POSTs once auth_enforcement_enabled=true: the global CSRF
    middleware (src/auth/csrf.py) fires before @require() and rejects
    cross-origin state-changing requests with 403. requests.post() does not
    send Sec-Fetch-Site or Origin, so we set Origin explicitly to satisfy
    the same-origin fallback check.
    """
    parsed = urlparse(base_url)
    return {"Origin": f"{parsed.scheme}://{parsed.netloc}"}


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

    Post Stage-C flip (``auth_enforcement_enabled=true``), per-route
    ``@require(<perm>)`` decorators read ``flask.g.user``. Non-browser callers
    authenticate via ``Authorization: ApiKey <key>`` or ``X-API-Key``;
    ``load_api_key_user`` (gh-483) populates ``g.user`` with a synthetic admin
    service account on valid-key requests so ``@require()`` passes.
    """

    def test_api_rejects_missing_key(self, base_url: str, is_live: bool) -> None:
        if not is_live:
            pytest.skip("Auth enforcement tests only run against live deployment")
        r = requests.post(
            f"{base_url}/api/v2/decisions",
            json={},
            headers=_same_origin_headers(base_url),
            timeout=10,
        )
        assert r.status_code == 401, f"Expected 401 for missing key, got {r.status_code}"

    def test_api_rejects_invalid_key(self, base_url: str, is_live: bool) -> None:
        if not is_live:
            pytest.skip("Auth enforcement tests only run against live deployment")
        r = requests.post(
            f"{base_url}/api/v2/decisions",
            json={},
            headers={"X-API-Key": "not-the-real-key", **_same_origin_headers(base_url)},
            timeout=10,
        )
        assert r.status_code == 401, f"Expected 401 for invalid key, got {r.status_code}"

    def test_api_accepts_valid_key(self, base_url: str, api_key: str, is_live: bool) -> None:
        if not is_live:
            pytest.skip("Auth enforcement tests only run against live deployment")
        # POST /api/v2/decisions with a valid key should get past auth (400/422 for bad
        # payload is acceptable — what we're testing is that auth passes, not business logic)
        r = requests.post(
            f"{base_url}/api/v2/decisions",
            json={},
            headers={"X-API-Key": api_key, **_same_origin_headers(base_url)},
            timeout=10,
        )
        assert r.status_code != 401, f"Expected auth to pass with valid key, got {r.status_code}"
