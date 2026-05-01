"""
``require(permission)`` — Flask route decorator factory.

Enforces that the current user (``flask.g.user``) holds the given permission
before the route handler runs.  The permission is resolved from
``g.user.role`` via the ``ROLE_PERMISSIONS`` map in ``src.auth.permissions``.

Error behaviour (per spec §Error Behavior):
  - Unauthenticated (``g.user is None``):
      - API request (``Accept: application/json``): return 401 JSON.
      - HTML request: redirect to ``/auth/login`` with ``?next=<path>``.
        Until the login route exists (Stage A5), returns 401 HTML.
  - Authenticated but lacks permission:
      - API request: return 403 JSON.
      - HTML request: render access-denied page (503 until template exists,
        falls back to 403 JSON if template is missing at runtime).

Usage::

    from src.auth.middleware import require
    from src.auth.permissions import DECISION_WRITE

    @app.route("/v2/review/decide", methods=["POST"])
    @require(DECISION_WRITE)
    def submit_decision():
        ...

The decorator is a **no-op** during Stage A/B (before ``auth_enforcement_enabled``
is true) because routes do not yet call it.  Installing it on a route now
allows Stage C to switch enforcement on per-route without a second diff.

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
