"""
Dev-bypass guard for the auth system.

AUTH_DEV_BYPASS=1 allows unauthenticated access in local development.
It must NEVER be set in production (APP_ENV=production). The guard in
verify_dev_bypass_safe() enforces this — it is called at the top of
create_app() before any Flask config is loaded, so a misconfigured
production deploy fails fast at startup rather than silently allowing
unrestricted access.

Once A3 (session management) lands, dev_bypass_user() should import
SessionUser from src.auth.sessions rather than using the local dataclass.
"""

import os
import sys
import types
from dataclasses import dataclass, field


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


# ---------------------------------------------------------------------------
# Placeholder SessionUser for dev-bypass local/test use.
# TODO(A3): replace this with an import from src.auth.sessions once that
# module ships.  Keep the field names aligned with whatever A3 defines so
# callers need only update the import line.
# ---------------------------------------------------------------------------


@dataclass
class _DevBypassUser:
    """Synthetic admin user injected when AUTH_DEV_BYPASS=1 in development."""

    user_id: str = "dev-bypass"
    email: str = "dev@localhost"
    name: str = "Dev Bypass User"
    roles: list[str] = field(default_factory=lambda: ["admin"])
    is_authenticated: bool = True


def dev_bypass_user() -> types.SimpleNamespace:
    """
    Return a synthetic admin-role user for local development / tests.

    This is only valid when is_dev_bypass_enabled() is True; callers are
    responsible for that check.  The returned object is a SimpleNamespace
    so downstream code can read attributes without importing a specific class.

    Once A3 lands, this function should return a proper SessionUser instance.
    """
    user = _DevBypassUser()
    return types.SimpleNamespace(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        roles=user.roles,
        is_authenticated=user.is_authenticated,
    )
