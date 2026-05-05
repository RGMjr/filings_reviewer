"""
Generic ``feature_flags`` table reader with TTL cache.

Mirrors the SQL pattern in ``src/auth/csrf.py::_read_enforcement_flag`` but
generalised across keys. The cache is per-key — each flag tracks its own
``(value, fetched_at)`` so a hot flag doesn't keep a stale read of a
neighbouring one alive.

Cache hit path: zero DB round-trips. Cache-miss path issues one ``SELECT``.

Failure semantics: any DB error returns ``False`` (and logs a warning) so
the middleware that consumes a flag never crashes a request because of a
flag-table outage. This matches the safe-default semantics A4 chose for
``auth_enforcement_enabled``.

The table schema (from ``sql/202605012028_create_auth_foundation_tables.sql``):

    feature_flags(
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,           -- 'true' / 'false'
        expires_at  TIMESTAMPTZ,              -- nullable; non-null = emergency override
        actor       UUID REFERENCES auth_users(id),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )

A row with ``expires_at < NOW()`` is treated as off (the override has lapsed)
even if ``value='true'``.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Exception types that signal a programmer / configuration error — these should
# propagate rather than being silently swallowed and defaulting to False.
_PROGRAMMER_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    ImportError,
    AttributeError,
    NameError,
)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_FLAG_CACHE: dict[str, tuple[bool, float]] = {}
_FLAG_CACHE_TTL: float = 5.0  # seconds — same TTL A4 chose for the CSRF flag.
_CACHE_LOCK = threading.Lock()


def _clear_cache_for_tests() -> None:
    """Clear the per-key cache. Test-only helper.

    Pytest fixtures call this between tests so a flag flip in one test
    doesn't bleed into the next. Not part of the public API — production
    code never calls it.
    """
    with _CACHE_LOCK:
        _FLAG_CACHE.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_enabled(flag_key: str, *, fail_closed: bool = False) -> bool:
    """Return True iff ``flag_key`` is set to ``'true'`` and not expired.

    Caches each key's value for ``_FLAG_CACHE_TTL`` seconds so the hot path
    on every request is a dict lookup, not a DB round-trip.

    Args:
        flag_key: The ``feature_flags.key`` value to read.
        fail_closed: If True, any exception (including transient DB errors) is
            re-raised rather than defaulting to False. Use for boot-time flag
            reads where silent failure is the wrong default.

    Returns:
        Boolean — ``True`` if the row exists, ``value == 'true'``, and
        ``expires_at`` is either NULL or in the future.
    """
    now = time.monotonic()

    cached = _FLAG_CACHE.get(flag_key)
    if cached is not None:
        value, cached_at = cached
        if now - cached_at < _FLAG_CACHE_TTL:
            return value

    # Cache miss or expired — re-read from DB.
    enabled = _read_flag_from_db(flag_key, fail_closed=fail_closed)

    with _CACHE_LOCK:
        _FLAG_CACHE[flag_key] = (enabled, now)

    return enabled


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_flag_from_db(flag_key: str, *, fail_closed: bool = False) -> bool:
    """Read *flag_key* from ``feature_flags`` and return the resolved bool.

    Returns ``False`` on any DB error (connection, missing table, etc.) so
    the cache layer can keep going even if the DB is briefly unavailable.

    The expiry check happens in SQL — one round-trip, against the DB's clock
    rather than the app server's, so a clock-skewed app doesn't see flags
    differently from the rest of the system.
    """
    try:
        from src.web.app import get_db

        db = get_db()
        rows = db.query(
            """
            SELECT value
            FROM feature_flags
            WHERE key = %(flag_key)s
              AND (expires_at IS NULL OR expires_at > NOW())
            LIMIT 1
            """,
            {"flag_key": flag_key},
        )
    except Exception as exc:
        if fail_closed or isinstance(exc, _PROGRAMMER_ERRORS):
            logger.error(
                "feature_flags.is_enabled(%s): unexpected error (re-raising): %s",
                flag_key,
                exc,
            )
            raise
        logger.warning(
            "feature_flags.is_enabled(%s): DB read failed (defaulting to False): %s",
            flag_key,
            exc,
        )
        return False

    if not rows:
        return False

    return rows[0]["value"] == "true"
