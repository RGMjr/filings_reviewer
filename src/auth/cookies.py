"""
Session cookie helpers for the auth system.

Cookie attributes (per spec §Session Behavior and OWASP best practices):
  - HttpOnly: always on — prevents XSS scripts from reading the cookie.
  - SameSite=Lax: default — prevents CSRF from cross-site navigations while
    allowing GET navigation links (needed for OAuth redirect flows).
  - Secure: on in production, off in development — ``Secure`` requires HTTPS,
    which is unavailable on ``http://localhost`` during local development.
    Production traffic always terminates on HTTPS (Render terminates TLS at
    the proxy level).

The cookie holds only the opaque session id (UUID). No user data is encoded
in the cookie value — all identity information is stored server-side in the
``auth_sessions`` / ``auth_users`` tables.

Configuration:
  AUTH_SESSION_COOKIE_NAME  env var (default: ``auth_session_dev``)
  APP_ENV                   env var (``production`` enables Secure attribute)
"""

from __future__ import annotations

import os

from flask import Response


def _cookie_name() -> str:
    """Return the session cookie name from ``AUTH_SESSION_COOKIE_NAME``.

    Defaults to ``auth_session_dev`` in development/test environments.
    Production deployments should set ``AUTH_SESSION_COOKIE_NAME=auth_session``
    (or another name) via the Render env group.
    """
    return os.environ.get("AUTH_SESSION_COOKIE_NAME", "auth_session_dev")


def _is_production() -> bool:
    """Return True when ``APP_ENV=production``."""
    return os.environ.get("APP_ENV", "development") == "production"


def set_session_cookie(response: Response, session_id: str) -> None:
    """Attach the session cookie to *response*.

    The ``Secure`` attribute is set only when ``APP_ENV=production``.
    In development (``APP_ENV=development`` or unset), ``Secure`` is omitted
    so the cookie works over ``http://localhost``.

    All other security attributes (``HttpOnly``, ``SameSite=Lax``) are always
    set regardless of environment.

    The ``max_age`` / ``expires`` attributes are intentionally omitted — the
    server-side expiry in ``auth_sessions.expires_at`` is the authoritative
    lifetime; the cookie itself is a session cookie from the browser's
    perspective (cleared on browser close), which provides an additional
    defence-in-depth logout on device.

    Args:
        response: Flask ``Response`` object to attach the cookie to.
        session_id: Opaque session id (UUID string) to store in the cookie.
    """
    secure = _is_production()

    response.set_cookie(
        _cookie_name(),
        session_id,
        httponly=True,
        samesite="Lax",
        secure=secure,
        # path defaults to "/" — accessible across all routes
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from *response* (logout).

    Sets the cookie with an empty value and ``max_age=0`` to instruct the
    browser to delete it immediately.

    Args:
        response: Flask ``Response`` object to clear the cookie on.
    """
    secure = _is_production()

    response.set_cookie(
        _cookie_name(),
        "",
        httponly=True,
        samesite="Lax",
        secure=secure,
        max_age=0,
    )


def get_session_id_from_request(request) -> str | None:  # type: ignore[type-arg]
    """Extract the session id from the incoming *request* cookie jar.

    Returns ``None`` if the cookie is absent or its value is empty.

    Args:
        request: Flask ``Request`` object.

    Returns:
        Session id string, or ``None``.
    """
    value = request.cookies.get(_cookie_name(), "").strip()
    return value if value else None
