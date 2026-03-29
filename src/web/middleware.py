"""
Shared Flask middleware for the review application.

Provides reusable before_request/after_request hooks for:
- API key authentication
- Request timing
- Audit log insertion
"""

import hmac
import logging
import time
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, session

logger = logging.getLogger(__name__)


def register_api_auth(bp: Blueprint) -> None:
    """
    Register API key authentication as a before_request hook on a blueprint.

    Checks the X-API-Key header. Returns 401 if missing or invalid.
    Skips authentication if API_KEY_REQUIRED is False (development mode).
    """
    @bp.before_request
    def _check_api_key():
        if not current_app.config.get("API_KEY_REQUIRED", True):
            return None

        api_key = request.headers.get("X-API-Key")
        expected_key = current_app.config.get("API_KEY")

        if not expected_key:
            logger.error("API_KEY_REQUIRED is True but API_KEY is not configured")
            return jsonify({"status": "error", "message": "Server misconfigured"}), 500

        if not api_key:
            logger.warning(
                f"Missing API key for {request.method} {request.path} "
                f"from {request.remote_addr}"
            )
            return jsonify({"status": "error", "message": "API key required"}), 401

        if not hmac.compare_digest(api_key, expected_key):
            logger.warning(
                f"Invalid API key for {request.method} {request.path} "
                f"from {request.remote_addr}"
            )
            return jsonify({"status": "error", "message": "Invalid API key"}), 401

        return None


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
    candidate_id: int | None = None,
    filing_id: int | None = None,
    query_params: dict | None = None,
) -> Any:
    """
    Insert an audit log entry for the current request.

    Extracts common fields (timing, session, IP, user agent, route) automatically.
    Callers supply the blueprint-specific context (candidate_id, filing_id, query_params).

    Returns the response unchanged so it can be used in after_request hooks:
        return insert_audit_log_entry(response, candidate_id=..., ...)
    """
    from src.web.app import get_db

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
            candidate_id=candidate_id,
            query_params=query_params,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")

    return response
