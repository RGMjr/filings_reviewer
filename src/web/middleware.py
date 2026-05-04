"""
Shared Flask middleware for the review application.

Provides reusable before_request/after_request hooks for:
- API key authentication (non-browser callers via ``Authorization: ApiKey``
  or ``X-API-Key`` header — same-origin browser bypass removed in PR-C1)
- Admin gate (transitional — will be replaced by role lookup against
  auth_users when Stage A2 of the auth rollout lands; see
  docs/architecture/auth-rollout-implementation-plan.md)
- Request timing
- Audit log insertion

PR-C1 change: the same-origin browser bypass (``_is_same_origin()`` early
return inside ``_verify_api_key``) has been removed.  Browser traffic now
authenticates exclusively via session cookie (``require()`` decorators from
``src.auth.middleware``).  Non-browser callers authenticate via the
``X-API-Key`` / ``Authorization: ApiKey`` header path, which is preserved.
The ``register_api_auth`` blueprint-wide hook has also been removed; routes
that need per-endpoint API-key checks can still use ``require_api_key``.
"""

import functools
import hmac
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, session

logger = logging.getLogger(__name__)


def _verify_api_key() -> Any:
    """
    Core API-key check. Returns None to pass, or a Flask response tuple
    (body, status) to reject. Callable from a before_request hook or a
    per-route decorator.

    Authenticates non-browser callers via:
      - ``X-API-Key: <key>`` header
      - ``?api_key=<key>`` query parameter
      - ``Authorization: ApiKey <key>`` header

    The same-origin browser bypass has been removed (PR-C1). Browser traffic
    authenticates via session cookie through ``require()`` decorators.
    """
    if not current_app.config.get("API_KEY_REQUIRED", True):
        return None

    # Accept Authorization: ApiKey <key> in addition to X-API-Key header.
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if not api_key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("ApiKey "):
            api_key = auth_header[len("ApiKey ") :]

    expected_key = current_app.config.get("API_KEY")

    if not expected_key:
        logger.error("API_KEY_REQUIRED is True but API_KEY is not configured")
        return jsonify({"status": "error", "message": "Server misconfigured"}), 500

    if not api_key:
        logger.warning(
            f"Missing API key for {request.method} {request.path} from {request.remote_addr}"
        )
        return jsonify({"status": "error", "message": "API key required"}), 401

    if not hmac.compare_digest(api_key, expected_key):
        logger.warning(
            f"Invalid API key for {request.method} {request.path} from {request.remote_addr}"
        )
        return jsonify({"status": "error", "message": "Invalid API key"}), 401

    return None


def require_api_key(view: Callable) -> Callable:
    """
    Per-route API-key guard. Use on individual view functions when the
    containing blueprint is not fully guarded via `register_api_auth`
    (e.g., a mixed blueprint where HTML pages are intentionally public but
    specific endpoints need auth).
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        rejection = _verify_api_key()
        if rejection is not None:
            return rejection
        return view(*args, **kwargs)

    return wrapper


def require_admin(view: Callable) -> Callable:
    """Gate a view to admin reviewers only.

    Reads the comma-separated allowlist from env var ``ADMIN_USER_IDS``
    and matches against ``reviewer_id`` from the JSON body, query string,
    or ``X-Reviewer-Id`` header (in that order, mirroring the per-metric
    image-confirmation contract). Returns HTTP 403 ``{error:
    "admin_required"}`` when the env var is unset/empty or the reviewer
    isn't on the list.

    **Transitional.** This is a stop-gap admin gate until Stage A2 of
    the auth rollout lands (`src/auth/middleware.py::require(<permission>)`,
    role lookup against ``auth_users``). Migration is mechanical — swap
    ``@require_admin`` for ``@require('<permission>')`` on each call site.
    See ``docs/architecture/auth-rollout-implementation-plan.md``.
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        data = request.get_json(silent=True) or {}
        reviewer = (
            data.get("reviewer_id")
            or request.args.get("reviewer_id")
            or request.headers.get("X-Reviewer-Id")
            or ""
        ).strip()

        admins_csv = os.environ.get("ADMIN_USER_IDS", "")
        admins = frozenset(e.strip() for e in admins_csv.split(",") if e.strip())

        if not admins or reviewer not in admins:
            logger.warning(
                "Admin-only endpoint blocked: reviewer=%r path=%s",
                reviewer or "<missing>",
                request.path,
            )
            return jsonify({"error": "admin_required"}), 403
        return view(*args, **kwargs)

    return wrapper


def register_timing(bp: Blueprint) -> None:
    """
    Register request timing as a before_request hook on a blueprint.

    Stores g.request_start_time for use in after_request audit logging.
    """

    @bp.before_request
    def _log_request_start():
        g.request_start_time = time.time()


def insert_audit_log_entry(
    response: Any,
    filing_id: int | None = None,
    query_params: dict | None = None,
) -> Any:
    """
    Insert a v2_audit_log entry for the current request.

    Extracts common fields (timing, session, IP, user agent, route) automatically.
    Callers supply the blueprint-specific context (filing_id, query_params).

    Returns the response unchanged so it can be used in after_request hooks:
        return insert_audit_log_entry(response, filing_id=..., ...)
    """
    from src.web.app import get_db

    testing = bool(current_app.config.get("TESTING"))
    try:
        response_time_ms = None
        if hasattr(g, "request_start_time"):
            response_time_ms = int((time.time() - g.request_start_time) * 1000)

        db = get_db()
        db.insert_audit_log(
            session_id=session.get("_id"),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            route_name=request.endpoint or "unknown",
            http_method=request.method,
            url_path=request.path,
            filing_id=filing_id,
            query_params=query_params,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        if testing:
            logger.debug(f"Failed to insert audit log: {e}")
        else:
            logger.error(f"Failed to insert audit log: {e}")

    return response
