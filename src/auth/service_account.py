"""
Synthetic ``SessionUser`` for non-browser API-key callers.

Stage-C ``@require()`` decorators read ``flask.g.user``; this module supplies
that identity for callers using ``Authorization: ApiKey <key>`` or ``X-API-Key``
headers so post-flag-flip automation continues to pass authorization.

Scope is ``admin`` to preserve the pre-Stage-C blanket access of the API key.
Tighten the role here (e.g. to ``'reviewer'``) if the operator wants narrower
scope — see ``docs/operations/auth-stage-c-runbook.md`` §3.5.

The bridge is wired into the request lifecycle by ``load_api_key_user`` in
``src/auth/load_user.py``, which runs as a ``before_request`` hook immediately
after ``load_session_user``.
"""

from __future__ import annotations

import hmac

from flask import current_app, request

from src.auth.sessions import SessionUser

#: UUID sentinel for the synthetic service account.  Not present in
#: ``auth_users`` — by design, so the row stays out of allowlist management.
SERVICE_ACCOUNT_ID = "00000000-0000-0000-0000-000000000000"

_SERVICE_ACCOUNT = SessionUser(
    id=SERVICE_ACCOUNT_ID,
    email="api-key@service.local",
    display_name="API Key Service Account",
    role="admin",
    account_status="active",
)


def service_account_user() -> SessionUser:
    """Return the singleton service-account ``SessionUser``."""
    return _SERVICE_ACCOUNT


def try_api_key_authentication() -> SessionUser | None:
    """Return the service-account user if the request carries a valid API key.

    Returns ``None`` when:
      - ``API_KEY_REQUIRED`` is False (dev / test default).
      - No API key is present on the request.
      - The supplied key does not match ``current_app.config['API_KEY']``.
      - ``API_KEY`` is unset (misconfigured deploy — fail closed so ``@require()``
        ultimately 401s anonymous instead of silently elevating to admin).

    Accepts the same three input shapes as ``_verify_api_key`` in
    ``src/web/middleware.py`` (kept in sync intentionally — no shared helper
    yet, the duplication is four lines).
    """
    if not current_app.config.get("API_KEY_REQUIRED", True):
        return None

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if not api_key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("ApiKey "):
            api_key = auth_header[len("ApiKey ") :]
    if not api_key:
        return None

    expected = current_app.config.get("API_KEY")
    if not expected:
        return None

    if hmac.compare_digest(api_key, expected):
        return _SERVICE_ACCOUNT
    return None
