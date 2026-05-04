"""
Enforcement-timing helpers for the auth rollout.

``enforcement_started_at()`` returns the ``feature_flags.updated_at`` timestamp
for the ``auth_enforcement_enabled`` flag when it is currently active, or
``None`` when the flag is off or absent.

This is the single authoritative read for the 4-hour legacy-session bound
implemented in ``src.auth.load_user`` / ``src.auth.sessions``.

Why not use ``feature_flags.is_enabled()``?
    ``is_enabled()`` only returns a bool.  The 4-hour bound check needs the
    *timestamp* of when the flag was set to ``'true'``.  This module issues a
    direct DB query via psycopg (same approach as ``src/auth/sessions.py``)
    rather than going through the Flask app context, so it is safe to call from
    ``load_session_user`` (a before_request hook) before any route handler runs.

Caching:
    The result is cached in ``flask.g.enforcement_started_at`` for the lifetime
    of the request so a single request only pays one DB round-trip even if
    multiple code paths call ``enforcement_started_at()``.  There is no
    process-level cache — operators must be able to flip the flag and have the
    next request see the new value without a restart (even though Stage C's
    runbook pairs the flip with a restart, per-request reads are safer).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_ENFORCEMENT_FLAG_KEY = "auth_enforcement_enabled"


def enforcement_started_at() -> datetime | None:
    """Return the ``updated_at`` timestamp when ``auth_enforcement_enabled``
    was set to ``'true'``, or ``None`` if the flag is off or missing.

    Caches the result in ``flask.g`` for the duration of the current request.
    Falls back to a fresh DB read if called outside a Flask request context
    (e.g. from tests or CLI scripts).

    Returns:
        ``datetime`` (timezone-aware UTC) when enforcement is active, else
        ``None``.
    """
    # Try to serve from per-request cache to avoid repeated DB round-trips.
    try:
        from flask import g

        cached = g.get("_enforcement_started_at_fetched")
        if cached is not None:
            # Returns the value (could be None or a datetime).
            return g.get("_enforcement_started_at_value")
    except RuntimeError:
        # Outside Flask request context — skip cache.
        pass

    result = _read_enforcement_timestamp()

    try:
        from flask import g

        g._enforcement_started_at_fetched = True
        g._enforcement_started_at_value = result
    except RuntimeError:
        pass

    return result


def _read_enforcement_timestamp() -> datetime | None:
    """Issue a direct DB query to read ``auth_enforcement_enabled`` row.

    Returns the ``updated_at`` value when ``value='true'`` and not expired,
    otherwise ``None``.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.warning("enforcement_started_at: DATABASE_URL not set, returning None")
        return None

    try:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT updated_at
                FROM feature_flags
                WHERE key = %(key)s
                  AND value = 'true'
                  AND (expires_at IS NULL OR expires_at > NOW())
                LIMIT 1
                """,
                {"key": _ENFORCEMENT_FLAG_KEY},
            ).fetchone()

        if row is None:
            return None

        ts: datetime = row["updated_at"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts

    except Exception:
        logger.exception(
            "enforcement_started_at: DB read failed, treating enforcement as not started"
        )
        return None
