"""
Shared Flask middleware for the review application.

Provides reusable before_request/after_request hooks for:
- API key authentication
- Request timing
- Audit log insertion
"""

import functools
import hmac
import logging
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, session

logger = logging.getLogger(__name__)


def _is_same_origin() -> bool:
    """
    Return True if the request originates from the same host as the server.

    Checks Origin header first (reliable for POST fetch() calls; scheme-independent
    comparison handles HTTPS-terminating proxies where Flask sees http:// but the
    browser sends https://). Falls back to Referer header (sent for GET and
    same-origin navigations; browsers omit Origin for same-origin no-CORS
    GET/HEAD requests).

    Returns False if both headers are absent or point to a different host.
    """
    # Origin header check (scheme-independent host comparison).
    origin = request.headers.get("Origin", "")
    if origin and origin.split("://", 1)[-1] == request.host:
        return True

    # Referer fallback (scheme-independent host comparison — under
    # HTTPS-terminating proxies like Render, the Referer is https:// while
    # request.host_url is http://, so a startswith match would miss).
    referer = request.headers.get("Referer", "")
    if referer:
        referer_host = urllib.parse.urlsplit(referer).netloc
        if referer_host and referer_host == request.host:
            return True

    return False


def _verify_api_key() -> Any:
    """
    Core API-key check. Returns None to pass, or a Flask response tuple
    (body, status) to reject. Callable from a before_request hook or a
    per-route decorator.
    """
    if not current_app.config.get("API_KEY_REQUIRED", True):
        return None

    # Allow browser fetch calls from the same server (same-origin AJAX).
    if _is_same_origin():
        return None

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
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
    """
    Register API key authentication as a before_request hook on a blueprint.

    Checks the X-API-Key header. Returns 401 if missing or invalid.
    Skips authentication if API_KEY_REQUIRED is False (development mode).
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
