# src/auth — Authentication and authorization package.
# Stage A (foundation): session management (A3) and dev-bypass guard (A6).
# Permission catalog (A2), CSRF (A4), and OAuth (A5) land in subsequent PRs.
#
# Public re-exports for convenience:
from src.auth.sessions import SessionUser, create_session, lookup_session, revoke_session

__all__ = ["SessionUser", "create_session", "lookup_session", "revoke_session"]
