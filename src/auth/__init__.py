# src/auth — Authentication and authorization package.
# Stage A (foundation): permission catalog + require() middleware (A2),
# session management (A3), and dev-bypass guard (A6).
# CSRF (A4) and OAuth (A5) land in subsequent PRs.
#
# Public re-exports for convenience:
from src.auth.middleware import require
from src.auth.permissions import (
    ALL_PERMISSIONS,
    AUDIT_READ,
    DECISION_UNDO_ANY,
    DECISION_UNDO_OWN,
    DECISION_WRITE,
    FLAGS_MANAGE,
    INGEST_RUN,
    METRIC_ADD_MISSED,
    PROTECTED_READ,
    READINESS_READ,
    ROLE_PERMISSIONS,
    USERS_MANAGE,
    has_permission,
)
from src.auth.sessions import SessionUser, create_session, lookup_session, revoke_session

__all__ = [
    # Middleware
    "require",
    # Permission constants
    "ALL_PERMISSIONS",
    "AUDIT_READ",
    "DECISION_UNDO_ANY",
    "DECISION_UNDO_OWN",
    "DECISION_WRITE",
    "FLAGS_MANAGE",
    "INGEST_RUN",
    "METRIC_ADD_MISSED",
    "PROTECTED_READ",
    "READINESS_READ",
    "ROLE_PERMISSIONS",
    "USERS_MANAGE",
    "has_permission",
    # Session store
    "SessionUser",
    "create_session",
    "lookup_session",
    "revoke_session",
]
