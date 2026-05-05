"""
Shared Flask middleware for the review application.

Provides reusable before_request/after_request hooks for:
- API key authentication (non-browser callers via ``Authorization: ApiKey``
  or ``X-API-Key`` header — same-origin browser bypass removed in PR-C1)
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

    PR-C1 (transitional): the same-origin browser bypass remains active only
    while ``auth_enforcement_enabled`` is FALSE. Once the operator flips the
    flag, the bypass is gone and browser traffic must authenticate via
    session cookie through ``@require()`` decorators. This keeps existing
    embedded-image flows (e.g. ``<img src="/v2/review/image_crop/...">``)
    working in the gap between C1 merge and the flag flip.
    """
    if not current_app.config.get("API_KEY_REQUIRED", True):
        return None

    # Transitional same-origin bypass — only while enforcement is off.
    try:
        from src.auth.feature_flags import is_enabled

        if not is_enabled("auth_enforcement_enabled"):
            from src.auth.csrf import _is_same_origin

            if _is_same_origin():
                return None
    except Exception:
        # Flag lookup failure → treat as enforcement-on (skip bypass).
        # Safer default: an attacker shouldn't get the bypass via a DB outage.
        pass

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


def register_api_auth(bp: Blueprint) -> None:
    """Register the API-key before_request hook on a blueprint.

    Transitional (PR-C1 → Stage-C flag flip): wires ``_verify_api_key`` as a
    blueprint-scoped ``before_request`` hook so that non-browser callers must
    supply a valid ``X-API-Key`` / ``Authorization: ApiKey`` header even while
    ``auth_enforcement_enabled`` remains ``false``.  Once the operator flips
    the flag, ``@require()`` decorators take over as the authoritative gate and
    this hook becomes redundant (but harmless — ``_verify_api_key`` already
    skips same-origin browser requests and is a no-op when ``API_KEY_REQUIRED``
    is ``false``, which covers tests and dev).

    Remove this call (and this function) after the Stage-C flag has been flipped
    in production and the transition period for existing callers is over.
    """

    @bp.before_request
    def _check_api_key():
        return _verify_api_key()


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
