"""
CSRF protection middleware for the review application.

Implements a before_request hook (csrf_protect) that:
  - Is a no-op for safe HTTP methods (GET, HEAD, OPTIONS).
  - Is a no-op for paths starting with /auth/ (OAuth callbacks use state param).
  - Is a no-op when the auth_enforcement_enabled feature flag is off or missing.
  - When the flag is on: allows requests with Sec-Fetch-Site: same-origin header,
    then falls back to Origin/Referer same-origin check via _is_same_origin().
  - Returns 403 JSON for definitively cross-origin state-changing requests.

Flag value is cached for ~5 seconds (module-level tuple) to avoid a DB
round-trip on every request. The cache is cleared whenever the TTL expires so
a flag flip takes effect within one cache window.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any

from flask import jsonify, request

logger = logging.getLogger(__name__)


def _is_same_origin() -> bool:
    """Return True if the request originates from the same host as the server.

    Checks Origin first (reliable for POST fetch() calls; scheme-independent
    so HTTPS-terminating proxies don't mask same-origin), then Referer (sent
    for GET and same-origin navigations; browsers omit Origin for same-origin
    no-CORS GET/HEAD requests).

    Moved here from src/web/middleware.py in PR-C1 — CSRF is now the only
    caller. The previous use as an API-key bypass was removed.
    """
    origin = request.headers.get("Origin", "")
    if origin and origin.split("://", 1)[-1] == request.host:
        return True

    referer = request.headers.get("Referer", "")
    if referer:
        referer_host = urllib.parse.urlsplit(referer).netloc
        if referer_host and referer_host == request.host:
            return True

    return False


# ---------------------------------------------------------------------------
# Module-level flag cache: (value: bool, cached_at: float) | None
# ---------------------------------------------------------------------------
_FLAG_CACHE: tuple[bool, float] | None = None
_FLAG_CACHE_TTL: float = 5.0  # seconds


def _read_enforcement_flag() -> bool:
    """
    Read the auth_enforcement_enabled flag from the feature_flags table.

    Caches the result for _FLAG_CACHE_TTL seconds. Returns False if the row
    is absent or if the DB read fails (safe default — no-op during pre-enforcement
    stages of the rollout).
    """
    global _FLAG_CACHE

    now = time.monotonic()
    if _FLAG_CACHE is not None:
        value, cached_at = _FLAG_CACHE
        if now - cached_at < _FLAG_CACHE_TTL:
            return value

    # Cache miss or expired — re-read from DB.
    try:
        from src.web.app import get_db

        db = get_db()
        rows = db.query(
            "SELECT value FROM feature_flags WHERE key = 'auth_enforcement_enabled' LIMIT 1"
        )
        if not rows:
            # Row absent — default off (safe for pre-enforcement deployment).
            logger.debug(
                "auth_enforcement_enabled flag row absent in feature_flags; defaulting to False"
            )
            enabled = False
        else:
            enabled = rows[0]["value"] == "true"
    except Exception as exc:
        # Programmer / configuration errors (wrong context, import failures, etc.)
        # should propagate loudly rather than silently defaulting to off.
        # Transient DB errors (connection failure, table not yet applied, etc.)
        # default off so the middleware stays safe before the DB is fully available.
        _programmer_errors = (RuntimeError, ImportError, AttributeError, NameError)
        if isinstance(exc, _programmer_errors):
            logger.error(
                "csrf_protect: programmer error reading auth_enforcement_enabled flag (re-raising): %s",
                exc,
            )
            raise
        logger.warning(
            "csrf_protect: failed to read auth_enforcement_enabled flag (defaulting to False): %s",
            exc,
        )
        enabled = False

    _FLAG_CACHE = (enabled, now)
    return enabled


def csrf_protect() -> Any:
    """
    Flask before_request hook: reject cross-origin state-changing requests when
    auth_enforcement_enabled is on.

    Called automatically for every request via app.before_request(csrf_protect).
    Returns None to allow the request to proceed, or a 403 JSON response to
    reject it before any route handler runs.
    """
    # Safe methods carry no state-changing side effects — never block.
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None

    # /auth/ prefix is exempt: OAuth callback relies on the state parameter
    # for CSRF protection rather than this header-based mechanism.
    if request.path.startswith("/auth/"):
        return None

    # If enforcement is off (or flag is missing), this middleware is a no-op.
    if not _read_enforcement_flag():
        return None

    # Sec-Fetch-Site is set by modern browsers for all cross-site navigations and
    # is not forgeable by cross-origin JavaScript. If it says same-origin, allow.
    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "")
    if sec_fetch_site == "same-origin":
        return None

    # Fallback: Origin / Referer host comparison.
    if _is_same_origin():
        return None

    # Definitively cross-origin — reject.
    logger.warning(
        "csrf_protect: cross-origin %s %s blocked (Sec-Fetch-Site=%r, remote=%s)",
        request.method,
        request.path,
        sec_fetch_site,
        request.remote_addr,
    )
    return jsonify({"error": "CSRF check failed"}), 403
