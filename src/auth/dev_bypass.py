"""
Dev-bypass guard for the auth system.

AUTH_DEV_BYPASS=1 allows unauthenticated access in local development.
It must NEVER be set in production (APP_ENV=production). The guard in
verify_dev_bypass_safe() enforces this — it is called at the top of
create_app() before any Flask config is loaded, so a misconfigured
production deploy fails fast at startup rather than silently allowing
unrestricted access.

dev_bypass_user() returns a real ``SessionUser`` (the same dataclass the
OAuth path produces) so downstream consumers — the require() decorator,
audit-log writers, role checks — see one shape for both code paths.
"""

import os
import sys

from src.auth.sessions import SessionUser

# Stable UUID assigned to the dev-bypass synthetic user. Constant so audit
# rows from local dev runs collate cleanly (instead of a different random
# UUID per process). Not a real ``auth_users`` row — never insert it.
DEV_BYPASS_USER_ID = "00000000-0000-0000-0000-000000000000"


def is_dev_bypass_enabled() -> bool:
    """Return True if AUTH_DEV_BYPASS is set to exactly '1'."""
    return os.environ.get("AUTH_DEV_BYPASS", "").strip() == "1"


def verify_dev_bypass_safe() -> None:
    """
    Raise RuntimeError if both APP_ENV=production and AUTH_DEV_BYPASS=1 are set.

    Called at the very top of create_app() (before config load) so a
    misconfigured production container refuses to start rather than silently
    opening every route to anonymous access.
    """
    is_prod = os.environ.get("APP_ENV", "development") == "production"
    if is_prod and is_dev_bypass_enabled():
        msg = (
            "FATAL: AUTH_DEV_BYPASS=1 is set in a production environment (APP_ENV=production). "
            "This is a security misconfiguration. Unset AUTH_DEV_BYPASS before starting in production."
        )
        print(msg, file=sys.stderr)
        raise RuntimeError(msg)


def dev_bypass_user() -> SessionUser:
    """Return a synthetic admin-role ``SessionUser`` for local dev / tests.

    Only valid when ``is_dev_bypass_enabled()`` is True; callers are
    responsible for that check. The returned dataclass has the same shape
    as the OAuth-flow user, so any code reading ``g.user.role`` etc. works
    against either path without a special case.
    """
    return SessionUser(
        id=DEV_BYPASS_USER_ID,
        email="dev@localhost",
        display_name="Dev Bypass User",
        role="admin",
        account_status="active",
    )
