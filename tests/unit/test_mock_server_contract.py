"""Mock server contract test — catches template context drift before it
nukes the Playwright suite.

When production routes in src/web/routes/review_unified.py add a new template
context variable, tests/ui/test_server.py must be updated in parallel. If
it isn't, mock-rendered routes return HTTP 500 and all Playwright tests
fail with cascading timeouts (~28 min of CI wasted per run).

This test renders the same 7 routes that smoke.spec.js exercises, but does
so via Flask's test_client in <5 seconds — catching the drift in the Unit
Tests job.

See KNOWN_ISSUES #28.
"""

import sys
from pathlib import Path

import pytest
from jinja2 import StrictUndefined

# Make tests/ui importable so we can load test_server's `app`
TESTS_UI_DIR = Path(__file__).parent.parent / "ui"
sys.path.insert(0, str(TESTS_UI_DIR))

from test_server import app  # noqa: E402, I001


# Must stay in sync with tests/ui/smoke.spec.js (TEMPLATE_ROUTES constant)
SMOKE_ROUTES = [
    "/",
    "/reviewed-fact",
    "/rejected-fact",
    "/no-facts",
    "/images-tab-empty",
    "/images-tab",
    "/images-tab-reviewed",
    "/images-tab-vision",
]


@pytest.fixture
def strict_client():
    """Flask test client with Jinja2 StrictUndefined so missing context
    variables raise UndefinedError instead of silently rendering as ''."""
    original_undefined = app.jinja_env.undefined
    app.jinja_env.undefined = StrictUndefined
    try:
        with app.test_client() as client:
            yield client
    finally:
        app.jinja_env.undefined = original_undefined


@pytest.mark.parametrize("route", SMOKE_ROUTES)
def test_mock_server_renders_route_without_undefined_vars(strict_client, route):
    """Each route Playwright smoke-tests must render 200 with no undefined
    Jinja vars. Regressions here almost always mean test_server.py's mock
    context drifted from what src/web/templates/unified_review.html expects.
    """
    response = strict_client.get(route)
    assert response.status_code == 200, (
        f"{route} returned {response.status_code} — mock context likely "
        f"missing a template variable. Compare test_server.py to "
        f"src/web/routes/review_unified.py. Body head: "
        f"{response.data[:500].decode(errors='replace')!r}"
    )
