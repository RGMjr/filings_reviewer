"""Integration tests for the @require() flag-on enforcement contract.

Walks every protected route registered by PR-C1 (39 routes across 6 modules)
with auth_enforcement_enabled=True and asserts:

  - unauthenticated  → 401 (JSON) or 302 redirect (HTML)
  - viewer/reviewer  → 403 when the role lacks the route's permission
  - admin            → status NOT IN {401, 403} (gate opens)

The third assertion is the regression catch: if a future PR drops a
@require() decorator, an admin would still be blocked by *something* only on
routes that have a stacked secondary gate (require_admin / require_api_key on
2 routes). On the other 37, removing @require() makes admin requests succeed
where they previously hit the gate -- this suite would not detect that
specific case directly, but the unauth + insufficient-role assertions DO fail
when the decorator is removed, since with no gate the route runs and returns
something other than 401/403.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from flask import g

from src.auth.permissions import (
    DECISION_UNDO_OWN,
    DECISION_WRITE,
    INGEST_RUN,
    METRIC_ADD_MISSED,
    PROTECTED_READ,
    ROLE_PERMISSIONS,
)
from src.auth.sessions import SessionUser

# ---------------------------------------------------------------------------
# Route registry — the authoritative list of protected routes from PR-C1.
# Re-derive from `grep -n "@require(" src/web/routes/*.py` if a route is
# added or removed.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    module: str
    method: str
    path: str
    perm: str
    stacked_outer_gate: bool = False  # has @require_admin or @require_api_key


_UUID = "00000000-0000-0000-0000-000000000000"


ROUTES: tuple[Route, ...] = (
    # api_unified (17)
    Route("api_unified", "POST", "/api/v2/decisions", DECISION_WRITE),
    Route("api_unified", "DELETE", "/api/v2/decisions/1", DECISION_UNDO_OWN),
    Route("api_unified", "POST", "/api/v2/image-candidates/bulk-reject", DECISION_WRITE),
    Route("api_unified", "POST", "/api/v2/image-candidates/bulk-undo", DECISION_UNDO_OWN),
    Route("api_unified", "POST", f"/api/v2/image-candidates/{_UUID}/skip", DECISION_WRITE),
    Route("api_unified", "POST", f"/api/v2/image-candidates/{_UUID}/unskip", DECISION_WRITE),
    Route("api_unified", "POST", f"/api/v2/image-candidates/{_UUID}/reopen", DECISION_UNDO_OWN),
    Route("api_unified", "POST", "/api/v2/missed-metric", METRIC_ADD_MISSED),
    Route("api_unified", "GET", "/api/v2/metrics/list", PROTECTED_READ),
    Route("api_unified", "POST", "/api/v2/image-metric-confirmations", DECISION_WRITE),
    Route(
        "api_unified", "DELETE", f"/api/v2/image-metric-confirmations/{_UUID}", DECISION_UNDO_OWN
    ),
    Route("api_unified", "POST", "/api/v2/models/image-classifier/retrain", INGEST_RUN),
    Route("api_unified", "GET", f"/api/v2/models/training/{_UUID}/status", PROTECTED_READ),
    Route("api_unified", "POST", "/api/v2/extraction/analyze-text-decisions", INGEST_RUN),
    Route("api_unified", "GET", f"/api/v2/extraction/analysis-runs/{_UUID}/status", PROTECTED_READ),
    Route(
        "api_unified",
        "POST",
        "/api/v2/extraction/recommendation-decisions",
        INGEST_RUN,
        stacked_outer_gate=True,
    ),
    Route(
        "api_unified",
        "DELETE",
        f"/api/v2/extraction/recommendation-decisions/{_UUID}",
        INGEST_RUN,
        stacked_outer_gate=True,
    ),
    # api_ingest (3)
    Route("api_ingest", "GET", "/api/v2/ingest/batches/1/status", PROTECTED_READ),
    Route("api_ingest", "POST", "/api/v2/ingest/batches/1/cancel", INGEST_RUN),
    Route("api_ingest", "GET", "/api/v2/ingest/filter-options", PROTECTED_READ),
    # ingest (8)
    Route("ingest", "GET", "/ingest/", PROTECTED_READ),
    Route("ingest", "POST", "/ingest/preview", INGEST_RUN),
    Route("ingest", "POST", "/ingest/start", INGEST_RUN),
    Route("ingest", "POST", "/ingest/populate", INGEST_RUN),
    Route("ingest", "GET", "/ingest/history", PROTECTED_READ),
    Route("ingest", "GET", "/ingest/batch/1", PROTECTED_READ),
    Route("ingest", "POST", "/ingest/batch/1/resume", INGEST_RUN),
    Route("ingest", "POST", "/ingest/batch/1/reextract", INGEST_RUN),
    # review_unified (6)
    Route("review_unified", "GET", "/v2/review/", PROTECTED_READ),
    Route("review_unified", "GET", "/v2/review/filings", PROTECTED_READ),
    Route("review_unified", "GET", "/v2/review/stats", PROTECTED_READ),
    Route("review_unified", "GET", "/v2/review/1", PROTECTED_READ),
    Route("review_unified", "GET", "/v2/review/next-filing", PROTECTED_READ),
    Route(
        "review_unified",
        "GET",
        f"/v2/review/image_crop/{_UUID}",
        PROTECTED_READ,
        stacked_outer_gate=True,
    ),
    # review_pres_images (4)
    Route("review_pres_images", "GET", "/review/pres-images/", PROTECTED_READ),
    Route("review_pres_images", "GET", "/review/pres-images/somekey", PROTECTED_READ),
    Route("review_pres_images", "POST", "/review/pres-images/somekey/img1/decide", DECISION_WRITE),
    Route(
        "review_pres_images", "DELETE", "/review/pres-images/somekey/img1/decide", DECISION_UNDO_OWN
    ),
    # image_cache (1)
    Route("image_cache", "GET", "/images/cache/123/0001234567-23-000001/foo.png", PROTECTED_READ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_ADMIN_REVIEWER_ID = "test-admin-reviewer"
_TEST_USER_IDS: dict[str, str] = {
    "viewer": "00000000-0000-0000-0000-00000000000a",
    "reviewer": "00000000-0000-0000-0000-00000000000b",
    "admin": "00000000-0000-0000-0000-00000000000c",
}


def _make_user(role: str) -> SessionUser:
    return SessionUser(
        id=_TEST_USER_IDS[role],
        email=f"{role}@example.com",
        display_name=f"Test {role.title()}",
        role=role,
        account_status="active",
    )


@pytest.fixture
def force_enforcement_on(monkeypatch):
    """Force auth_enforcement_enabled=True for the @require() decorator path."""
    monkeypatch.setattr(
        "src.auth.feature_flags.is_enabled",
        lambda key, **_kwargs: key in ("auth_enforcement_enabled", "google_login_enabled"),
    )
    # csrf_protect bypasses is_enabled() — clear its module-level cache so any
    # prior test's value doesn't leak in.
    import src.auth.csrf as _csrf

    _csrf._FLAG_CACHE = None


@pytest.fixture
def app_with_user(oauth_app, force_enforcement_on, monkeypatch):
    """Returns a (set_user, client) factory.

    set_user(None | SessionUser) registers a before_request hook on oauth_app
    that overrides g.user *after* load_session_user runs (Flask executes
    before_request hooks in registration order, so a hook registered post-
    fixture runs last). oauth_app is function-scoped, so hooks don't leak
    across parametrize iterations.
    """
    # Skip the per-route api-key gate (only fires on /v2/review/image_crop/...
    # in the protected set). Setting API_KEY_REQUIRED=False makes
    # require_api_key a no-op so the @require(PROTECTED_READ) underneath is
    # what we exercise.
    oauth_app.config["API_KEY_REQUIRED"] = False

    # Don't re-raise exceptions out of the test client — when the gate opens
    # for admin and the view runs, downstream DB queries may fail (e.g.
    # missing fixtures). We want the test client to surface those as 500
    # rather than raising into the test, so admin-passes-gate sees a status
    # code (500 ≠ 401/403, so the gate-pass assertion still holds).
    oauth_app.config["PROPAGATE_EXCEPTIONS"] = False

    # Allow our admin user to pass require_admin (stacked above @require() on
    # the two /extraction/recommendation-decisions endpoints). Reviewer ids
    # for viewer/reviewer roles are intentionally NOT added — those tests
    # expect to be blocked anyway.
    monkeypatch.setenv("ADMIN_USER_IDS", _ADMIN_REVIEWER_ID)

    def _factory(user):
        @oauth_app.before_request
        def _inject_user():
            g.user = user

        return oauth_app.test_client()

    return _factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(client, route: Route, *, with_admin_id: bool = False):
    """Issue a request appropriate for the route type.

    Sets:
      - Accept: application/json on /api/* paths so 401/403 responses are JSON
        (test client default Accept: */* rounds to HTML, triggering redirect).
      - Sec-Fetch-Site: same-origin so csrf_protect doesn't reject non-GET
        requests before @require() runs.
      - X-Reviewer-Id: <admin-id> when with_admin_id=True, so require_admin
        on the two stacked routes lets us reach the @require() underneath.
    """
    headers = {"Sec-Fetch-Site": "same-origin"}
    kwargs: dict = {"method": route.method, "headers": headers}

    if route.path.startswith("/api/"):
        headers["Accept"] = "application/json"

    if with_admin_id:
        headers["X-Reviewer-Id"] = _ADMIN_REVIEWER_ID

    if route.method in ("POST", "PUT", "PATCH"):
        headers["Content-Type"] = "application/json"
        kwargs["data"] = "{}"

    return client.open(route.path, **kwargs)


def _route_id(r: Route) -> str:
    return f"{r.module}:{r.method} {r.path}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=_route_id)
def test_unauthenticated_blocked(route, app_with_user):
    client = app_with_user(None)  # g.user = None
    resp = _request(client, route)
    if route.path.startswith("/api/"):
        # JSON callers always get 401 (or 403 from a stacked outer gate that
        # rejects unauthenticated requests on its own terms).
        assert resp.status_code in (401, 403), (
            f"{_route_id(route)}: expected 401/403, got {resp.status_code}"
        )
    else:
        # HTML callers get 302 → /auth/login (or 401 fallback if login
        # blueprint isn't registered, or 403 from a stacked outer gate).
        assert resp.status_code in (302, 401, 403), (
            f"{_route_id(route)}: expected 302/401/403, got {resp.status_code}"
        )


@pytest.mark.parametrize("role", ["viewer", "reviewer"])
@pytest.mark.parametrize("route", ROUTES, ids=_route_id)
def test_insufficient_role_returns_403(route, role, app_with_user):
    if route.perm in ROLE_PERMISSIONS[role]:
        pytest.skip(f"{role} already has {route.perm}")

    client = app_with_user(_make_user(role))
    resp = _request(client, route)
    assert resp.status_code == 403, (
        f"{_route_id(route)} as {role}: expected 403, got {resp.status_code}"
    )


def _is_auth_gate_error(resp) -> bool:
    """Return True if a 401/403 came from @require() or the stacked outer
    gates (require_admin, require_api_key) — not from application-level
    validation (e.g. _require_reviewer_id, missing-record 403s).

    @require()'s error strings: "Authentication required" / "Forbidden"
    require_admin's error string:  "admin_required"
    require_api_key's error string: "API key required" / "Invalid API key"
    """
    try:
        data = resp.get_json(silent=True) or {}
    except Exception:
        return True  # non-JSON body: assume gate (HTML 403 template)
    err = (data.get("error") or "").lower()
    msg = (data.get("message") or "").lower()
    gate_markers = (
        "authentication required",
        "forbidden",
        "admin_required",
        "api key required",
        "invalid api key",
    )
    return any(m in err for m in gate_markers) or any(m in msg for m in gate_markers)


@pytest.mark.parametrize("route", ROUTES, ids=_route_id)
def test_admin_passes_gate(route, app_with_user):
    client = app_with_user(_make_user("admin"))
    resp = _request(client, route, with_admin_id=route.stacked_outer_gate)
    if resp.status_code in (401, 403):
        assert not _is_auth_gate_error(resp), (
            f"{_route_id(route)}: auth gate fired for admin "
            f"(status={resp.status_code}, body={resp.get_data(as_text=True)[:200]!r})"
        )
