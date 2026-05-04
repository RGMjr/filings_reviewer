"""
``require(permission)`` — Flask route decorator factory.

Enforces that the current user (``flask.g.user``) holds the given permission
before the route handler runs.  The permission is resolved from
``g.user.role`` via the ``ROLE_PERMISSIONS`` map in ``src.auth.permissions``.

**Flag-gating (PR-C1):** the decorator is a **true no-op** when the
``auth_enforcement_enabled`` feature flag is ``false`` (the default before
Stage C's operator flip).  In no-op mode the decorated view runs exactly as if
no decorator were present — unauthenticated users pass through, anonymous API
requests are not blocked.  This makes PR-C1 safe to merge before the operator
performs the Stage C flag flip: behaviour is unchanged until the operator sets
``auth_enforcement_enabled=true``.

When the flag is ``true`` the full enforcement path runs:

Error behaviour (per spec §Error Behavior):
  - Unauthenticated (``g.user is None``):
      - API request (``Accept: application/json``): return 401 JSON.
      - HTML request: redirect to ``/auth/login`` with ``?next=<path>``.
  - Authenticated but lacks permission:
      - API request: return 403 JSON.
      - HTML request: render access-denied page (falls back to 403 JSON if
        template is missing at runtime).

Usage::

    from src.auth.middleware import require
    from src.auth.permissions import DECISION_WRITE

    @app.route("/v2/review/decide", methods=["POST"])
    @require(DECISION_WRITE)
    def submit_decision():
        ...

``g.user`` is populated by ``load_session_user`` (``src.auth.load_user``),
which must be registered as a ``before_request`` hook on the Flask app.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

from flask import g, jsonify, redirect, request, url_for

from src.auth.permissions import has_permission

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flag-awareness helper
# ---------------------------------------------------------------------------


def _enforcement_enabled() -> bool:
    """Return True iff ``auth_enforcement_enabled`` is active.

    Reads via ``flask.g`` cache first (populated by ``enforcement_started_at``
    during the same request) to avoid a DB round-trip per decorated route.
    Falls back to a direct ``feature_flags.is_enabled`` call.

    Per-request reads (not a module-level cache) so the operator can flip the
    flag without a restart — though Stage C's runbook pairs the flip with a
    deploy/restart anyway, per-request reads are safer.
    """
    try:
        from src.auth.feature_flags import is_enabled

        return is_enabled("auth_enforcement_enabled")
    except Exception:
        # If flag lookup fails entirely (e.g. no DB yet), default to False
        # so a misconfigured deploy does not lock out all users.
        logger.warning("require(): flag lookup failed, defaulting enforcement to False")
        return False


# Type alias for Flask view functions.
_ViewFunc = Callable[..., Any]


def _wants_json() -> bool:
    """Return True when the client prefers JSON over HTML."""
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return (
        best == "application/json"
        and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def _unauthenticated_response() -> Any:
    """Return the appropriate 401 response for an unauthenticated request.

    API callers (``Accept: application/json``) receive JSON.
    HTML callers are redirected to ``/auth/login`` with a ``?next=`` param
    once that route exists; until then a 401 JSON response is returned.
    """
    if _wants_json():
        return jsonify(error="Authentication required"), 401

    # Attempt to redirect to the login page (Stage A5+).
    # url_for raises BuildError if the endpoint isn't registered yet.
    try:
        login_url = url_for("auth.login", next=request.path)
        return redirect(login_url, code=302)
    except Exception:
        # Login blueprint not yet registered — return 401 JSON as fallback.
        return jsonify(error="Authentication required"), 401


def _forbidden_response() -> Any:
    """Return the appropriate 403 response for an authenticated but unauthorized request."""
    if _wants_json():
        return jsonify(error="Forbidden"), 403

    # Attempt to render an access-denied template (added in Stage C).
    try:
        from flask import render_template

        return render_template("errors/403.html"), 403
    except Exception:
        return jsonify(error="Forbidden"), 403


def require(permission: str) -> Callable[[_ViewFunc], _ViewFunc]:
    """Decorator factory that enforces *permission* on a Flask route.

    Args:
        permission: A permission constant from ``src.auth.permissions``
                    (e.g. ``DECISION_WRITE``).

    Returns:
        A decorator that wraps the view function with an auth/authz check.

    Raises:
        Nothing — all errors are returned as HTTP responses.
    """

    def decorator(func: _ViewFunc) -> _ViewFunc:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Flag-gate: when auth_enforcement_enabled is false (the default
            # before the Stage C operator flip), the decorator is a true no-op.
            # This makes the PR safe to merge before the flag flip.
            if not _enforcement_enabled():
                return func(*args, **kwargs)

            user = g.get("user")

            if user is None:
                logger.debug(
                    "require(%s): unauthenticated request to %s",
                    permission,
                    request.path,
                )
                return _unauthenticated_response()

            if not has_permission(user.role, permission):
                logger.debug(
                    "require(%s): role=%s lacks permission for %s",
                    permission,
                    user.role,
                    request.path,
                )
                return _forbidden_response()

            return func(*args, **kwargs)

        return wrapper

    return decorator
