"""
Authentication utilities for the Flask API.

Provides API key authentication for protecting API routes.
"""

import hmac
import logging
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from flask import current_app, jsonify, request

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def require_api_key(f: Callable[P, T]) -> Callable[P, T]:
    """
    Decorator to require API key authentication for a route.

    Checks for API key in:
    1. X-API-Key header (preferred)
    2. api_key query parameter (fallback)

    If API_KEY_REQUIRED is False in config, authentication is bypassed
    (useful for local development).

    Returns:
        401 Unauthorized if key is missing or invalid
        500 Internal Server Error if server has no API key configured

    Usage:
        @bp.route("/protected")
        @require_api_key
        def protected_route():
            ...
    """

    @wraps(f)
    def decorated(*args: P.args, **kwargs: P.kwargs) -> T:
        # Check if authentication is required
        if not current_app.config.get("API_KEY_REQUIRED", True):
            return f(*args, **kwargs)

        # Get API key from request
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = current_app.config.get("API_KEY")

        # Server must have API key configured
        if not expected_key:
            logger.error("API_KEY_REQUIRED is True but API_KEY is not configured")
            return jsonify({"status": "error", "message": "Server misconfigured"}), 500

        # Client must provide API key
        if not api_key:
            logger.warning(
                f"Missing API key for {request.method} {request.path} "
                f"from {request.remote_addr}"
            )
            return (
                jsonify({"status": "error", "message": "API key required"}),
                401,
            )

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(api_key, expected_key):
            logger.warning(
                f"Invalid API key for {request.method} {request.path} "
                f"from {request.remote_addr}"
            )
            return (
                jsonify({"status": "error", "message": "Invalid API key"}),
                401,
            )

        return f(*args, **kwargs)

    return decorated
