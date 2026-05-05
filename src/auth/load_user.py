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
from src.auth.dev_bypass import dev_bypass_user, is_dev_bypass_enabled
from src.auth.enforcement import enforcement_started_at
from src.auth.sessions import SessionUser, lookup_session

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

    if is_dev_bypass_enabled():
        g.user = dev_bypass_user()
        return

    session_id = get_session_id_from_request(request)
    if not session_id:
        g.user = None
        return

    try:
        session_user = lookup_session(session_id)
    except Exception:
        # Never let a session-lookup failure break a request.
        logger.exception("load_session_user: unexpected error during lookup")
        g.user = None
        return

    if session_user is None:
        g.user = None
        return

    # 4-hour legacy-session bound (spec §Cutover Rules → Existing Open Pages
    # at Enforcement Time).  When auth_enforcement_enabled flips to true,
    # sessions created BEFORE the flip are forcibly invalidated 4 hours after
    # the flip, regardless of activity.
    g.user = _apply_legacy_session_bound(session_user, session_id)


def load_api_key_user() -> None:
    """Bridge non-browser API-key callers to ``flask.g.user``.

    Registered as a second ``before_request`` hook immediately after
    ``load_session_user`` (see ``src/web/app.py``).  When the session-cookie
    path did not authenticate the request and the caller supplied a valid
    API key (``Authorization: ApiKey <key>``, ``X-API-Key`` header, or
    ``?api_key=`` arg), populate ``g.user`` with the synthetic admin
    service-account ``SessionUser`` so per-route ``@require(<perm>)``
    decorators pass.

    This is the Stage-C bridge for ``gh-483``:  ``_verify_api_key`` in
    ``src/web/middleware.py`` only runs on routes decorated with
    ``@require_api_key`` (today, just ``image_crop``), not on the broader
    ``/api/v2/*`` surface that uses ``@require(<perm>)`` directly.  Without
    this hook, valid API-key requests would be rejected once
    ``auth_enforcement_enabled`` flips to true.
    """
    if g.get("user") is not None:
        return

    # Lazy import: keeps the module import graph identical to pre-bridge state
    # for tests that monkeypatch ``src.auth.load_user`` symbols, and keeps the
    # service-account dependency local to the call path.
    from src.auth.service_account import try_api_key_authentication

    user = try_api_key_authentication()
    if user is not None:
        g.user = user


_LEGACY_SESSION_GRACE_SECONDS = 4 * 3600  # 4 hours in seconds


def _apply_legacy_session_bound(user: SessionUser, session_id: str) -> SessionUser | None:
    """Return *user* unchanged, or None if the 4-hour legacy-session bound applies.

    The bound only applies when:
    1. ``auth_enforcement_enabled`` is currently active (has a timestamp).
    2. The session's ``created_at`` predates the enforcement flip.
    3. More than 4 hours have elapsed since the enforcement flip.

    When all three hold, the session is treated as expired and the user is
    forced to re-authenticate.  The session row is NOT deleted — the next
    ``require()`` check will redirect to login.

    Args:
        user: The ``SessionUser`` resolved from the session cookie.
        session_id: The raw session id (for log correlation).

    Returns:
        The original *user* when the bound does not apply, ``None`` otherwise.
    """
    from datetime import UTC, datetime, timedelta

    started_at = enforcement_started_at()
    if started_at is None:
        # Enforcement not yet active — no bound to apply.
        return user

    now = datetime.now(tz=UTC)
    grace_expires_at = started_at + timedelta(seconds=_LEGACY_SESSION_GRACE_SECONDS)

    if now <= grace_expires_at:
        # Still within the 4-hour grace window — session remains valid.
        return user

    # We need the session's created_at to determine whether it predates the flip.
    # Fetch it directly; failure is treated as "session is valid" (fail-open) to
    # avoid locking users out due to a DB hiccup.
    try:
        import os

        import psycopg
        from psycopg.rows import dict_row

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return user

        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT created_at FROM auth_sessions WHERE id = %s",
                (session_id,),
            ).fetchone()

        if row is None:
            # Session row gone — treat as expired (already handled by lookup_session).
            return None

        created_at: datetime = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        if created_at >= started_at:
            # Session was created after the enforcement flip — not a legacy session.
            return user

        # Session predates the enforcement flip AND 4h grace has elapsed.
        logger.info(
            "Legacy session %s rejected: created_at=%s predates enforcement flip at %s "
            "(grace expired at %s)",
            session_id[:8],
            created_at.isoformat(),
            started_at.isoformat(),
            grace_expires_at.isoformat(),
        )
        return None

    except Exception:
        logger.exception(
            "load_session_user: error checking legacy-session bound for %s, failing open",
            session_id[:8],
        )
        return user
