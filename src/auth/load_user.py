"""
``load_session_user`` — Flask ``before_request`` hook.

Reads the session cookie from each incoming request, resolves it against
the ``auth_sessions`` / ``auth_users`` tables via ``lookup_session``, and
stores the result in ``flask.g.user``.

  - ``flask.g.user`` is a ``SessionUser`` dataclass when authenticated.
  - ``flask.g.user`` is ``None`` when unauthenticated, session expired, or
    user disabled.

This hook is registered on the Flask app once, at the application factory
level (``src/web/app.py``). All routes that need the current user read
``flask.g.user`` directly — they do not call this function themselves.

The hook is deliberately a **no-op** when the cookie is absent — it sets
``g.user = None`` and returns immediately, adding no latency to anonymous
requests (e.g. /health checks, static-file routes).

Auth enforcement (redirecting unauthenticated users to login) is not applied
here — it lives in the permission-level ``require()`` decorator (PR-A2) and
route-level guards (Stage C). Until Stage C lands, ``g.user`` is informational
only; existing routes continue to use the ``FILINGS_API_KEY`` gate.
"""

from __future__ import annotations

import logging

from flask import g, request

from src.auth.cookies import get_session_id_from_request
from src.auth.sessions import lookup_session

logger = logging.getLogger(__name__)


def load_session_user() -> None:
    """Populate ``flask.g.user`` from the session cookie.

    Called automatically as a Flask ``before_request`` hook for every request.
    Idempotent — safe to call multiple times (subsequent calls are no-ops if
    ``g.user`` is already set).

    Side effects:
      - Sets ``g.user = SessionUser(...)`` when a valid session is found.
      - Sets ``g.user = None`` when no session is found or it is invalid.
    """
    # Idempotency guard: don't overwrite a value set by a test or earlier call.
    if "user" in g:
        return

    session_id = get_session_id_from_request(request)
    if not session_id:
        g.user = None
        return

    try:
        g.user = lookup_session(session_id)
    except Exception:
        # Never let a session-lookup failure break a request.
        logger.exception("load_session_user: unexpected error during lookup")
        g.user = None
