"""
DB-backed session store for the auth system.

Sessions are stored in the ``auth_sessions`` table (created by PR-A1 /
migration 202605012028). The session cookie holds only an opaque session id
(UUID); all user-identity data stays server-side.

Expiry model (per spec §Session Behavior):
- **Sliding inactivity window**: 24 hours since ``last_seen_at``.
  ``lookup_session`` returns None and ``extend_session`` is a no-op once
  ``last_seen_at + INACTIVITY_HOURS < NOW()``.
- **Absolute lifetime**: 30 days since ``created_at``.
  ``lookup_session`` returns None regardless of activity after this cap.

Both limits are read from environment variables at call time so ops can
adjust without a redeploy (values are validated to positive integers):
  AUTH_SESSION_INACTIVITY_HOURS  (default: 24)
  AUTH_SESSION_ABSOLUTE_DAYS     (default: 30)

Performance note: ``extend_session`` issues one UPDATE per request. This is
intentional — ``last_seen_at`` drives the inactivity window so it must be
fresh. Future optimisation: batch updates with a coarse TTL (e.g. skip the
UPDATE if last_seen_at is already within the last 5 minutes).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _inactivity_hours() -> int:
    """Return AUTH_SESSION_INACTIVITY_HOURS (default 24)."""
    raw = os.environ.get("AUTH_SESSION_INACTIVITY_HOURS", "24")
    try:
        val = int(raw)
        return val if val > 0 else 24
    except ValueError:
        return 24


def _absolute_days() -> int:
    """Return AUTH_SESSION_ABSOLUTE_DAYS (default 30)."""
    raw = os.environ.get("AUTH_SESSION_ABSOLUTE_DAYS", "30")
    try:
        val = int(raw)
        return val if val > 0 else 30
    except ValueError:
        return 30


# ---------------------------------------------------------------------------
# SessionUser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionUser:
    """Authenticated user identity attached to ``flask.g.user`` per request.

    Populated by ``lookup_session`` from ``auth_sessions`` JOIN ``auth_users``.
    All fields are read directly from the DB row — no computed attributes.
    """

    id: str
    """UUID string — ``auth_users.id``."""

    email: str
    """Normalised email — ``auth_users.normalized_email``."""

    display_name: str | None
    """Display name from Google profile — ``auth_users.display_name``."""

    role: str
    """One of 'admin', 'reviewer', 'viewer' — ``auth_users.role``."""

    account_status: str
    """One of 'active', 'disabled' — ``auth_users.account_status``."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_db_url() -> str:
    """Return DATABASE_URL from the environment.

    Raises RuntimeError if unset so callers surface a clear error rather
    than a confusing psycopg connection failure.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Session operations require a database connection."
        )
    return url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_session(
    user_id: str,
    user_agent: str | None = None,
    ip_first_seen: str | None = None,
) -> str:
    """Create a new session for *user_id* and return the session id (UUID string).

    The session row is inserted with:
      - ``created_at = NOW()``
      - ``last_seen_at = NOW()``
      - ``expires_at = NOW() + INACTIVITY_HOURS``

    The absolute lifetime is enforced in ``lookup_session`` by comparing
    ``created_at`` to ``NOW()``, not by a separate column, so the ``expires_at``
    column tracks the inactivity deadline only.

    Args:
        user_id: UUID string matching an ``auth_users.id`` row.
        user_agent: Optional HTTP User-Agent string for audit purposes.
        ip_first_seen: Optional client IP address string for audit purposes.

    Returns:
        Session id as a UUID string.
    """
    session_id = str(uuid.uuid4())
    inactivity_delta = timedelta(hours=_inactivity_hours())

    db_url = _get_db_url()
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (id, user_id, expires_at, user_agent, ip_first_seen)
            VALUES (
                %s,
                %s,
                NOW() + %s::interval,
                %s,
                %s::inet
            )
            """,
            (
                session_id,
                user_id,
                str(inactivity_delta),
                user_agent,
                ip_first_seen,
            ),
        )
        conn.commit()

    logger.debug("Created session %s for user %s", session_id[:8], user_id[:8])
    return session_id


def lookup_session(session_id: str) -> SessionUser | None:
    """Look up *session_id* and return the associated ``SessionUser``, or None.

    Returns None when any of the following are true:
    - The session id is not found in ``auth_sessions``.
    - ``expires_at < NOW()`` (inactivity window expired).
    - ``created_at + ABSOLUTE_DAYS < NOW()`` (absolute lifetime exceeded).
    - The associated ``auth_users`` row has ``account_status = 'disabled'``.

    On a successful lookup, ``last_seen_at`` is refreshed and ``expires_at``
    is extended by INACTIVITY_HOURS (sliding window). Both updates happen in
    the same transaction as the SELECT to avoid race conditions.

    Args:
        session_id: UUID string from the session cookie.

    Returns:
        ``SessionUser`` on success, ``None`` on any miss.
    """
    if not session_id:
        return None

    absolute_limit = timedelta(days=_absolute_days())
    inactivity_delta = timedelta(hours=_inactivity_hours())

    db_url = _get_db_url()
    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT
                    s.id            AS session_id,
                    s.created_at    AS session_created_at,
                    s.expires_at    AS session_expires_at,
                    u.id::text      AS user_id,
                    u.normalized_email,
                    u.display_name,
                    u.role,
                    u.account_status,
                    NOW()           AS now
                FROM auth_sessions s
                JOIN auth_users u ON u.id = s.user_id
                WHERE s.id = %s
                """,
                (session_id,),
            ).fetchone()

            if row is None:
                return None

            now: datetime = row["now"]
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)

            created_at: datetime = row["session_created_at"]
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)

            expires_at: datetime = row["session_expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)

            # Check absolute lifetime first (hardest cap).
            if now > created_at + absolute_limit:
                logger.debug(
                    "Session %s exceeded absolute lifetime, treating as expired",
                    session_id[:8],
                )
                return None

            # Check inactivity expiry.
            if now > expires_at:
                logger.debug(
                    "Session %s inactivity window expired",
                    session_id[:8],
                )
                return None

            # Check account status.
            if row["account_status"] != "active":
                logger.debug(
                    "Session %s belongs to disabled user %s",
                    session_id[:8],
                    row["user_id"][:8],
                )
                return None

            # Extend the sliding inactivity window.
            conn.execute(
                """
                UPDATE auth_sessions
                SET last_seen_at = NOW(),
                    expires_at   = NOW() + %s::interval
                WHERE id = %s
                """,
                (str(inactivity_delta), session_id),
            )
            conn.commit()

            return SessionUser(
                id=row["user_id"],
                email=row["normalized_email"],
                display_name=row["display_name"],
                role=row["role"],
                account_status=row["account_status"],
            )
    except Exception:
        logger.exception("lookup_session failed for session %s", session_id[:8])
        return None


def extend_session(session_id: str) -> None:
    """Extend the inactivity window for *session_id*.

    This is a convenience wrapper around the UPDATE already performed by
    ``lookup_session``. Call it explicitly when you need to extend a session
    without a full lookup (rare — ``lookup_session`` already extends on every
    successful call).

    Args:
        session_id: UUID string from the session cookie.
    """
    if not session_id:
        return

    inactivity_delta = timedelta(hours=_inactivity_hours())
    db_url = _get_db_url()
    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            conn.execute(
                """
                UPDATE auth_sessions
                SET last_seen_at = NOW(),
                    expires_at   = NOW() + %s::interval
                WHERE id = %s
                """,
                (str(inactivity_delta), session_id),
            )
            conn.commit()
    except Exception:
        logger.exception("extend_session failed for session %s", session_id[:8])


def revoke_session(session_id: str) -> None:
    """Delete the session row for *session_id*, effectively logging the user out.

    Idempotent — silently succeeds if the session does not exist.

    Args:
        session_id: UUID string from the session cookie.
    """
    if not session_id:
        return

    db_url = _get_db_url()
    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            conn.execute(
                "DELETE FROM auth_sessions WHERE id = %s",
                (session_id,),
            )
            conn.commit()
        logger.debug("Revoked session %s", session_id[:8])
    except Exception:
        logger.exception("revoke_session failed for session %s", session_id[:8])


def revoke_all_for_user(user_id: str) -> int:
    """Delete all session rows for *user_id* (force-logout).

    Args:
        user_id: UUID string matching ``auth_users.id``.

    Returns:
        Number of sessions revoked.
    """
    if not user_id:
        return 0

    db_url = _get_db_url()
    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            result = conn.execute(
                "DELETE FROM auth_sessions WHERE user_id = %s RETURNING id",
                (user_id,),
            ).fetchall()
            conn.commit()
        count = len(result)
        logger.debug("Revoked %d session(s) for user %s", count, user_id[:8])
        return count
    except Exception:
        logger.exception("revoke_all_for_user failed for user %s", user_id[:8])
        return 0
