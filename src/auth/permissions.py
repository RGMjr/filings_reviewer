"""
Permission catalog for the CMASB Review UI authorization system.

Defines the complete set of named permissions and the role→permission map.
Routes call ``require(<permission>)`` rather than ``require_role(<role>)``;
this keeps viewer-expansion possible without refactoring every route.

Permission names (from spec §Permission Catalog):

  protected.read    — read protected pages (review UI, stats UI, ingest history UI)
  readiness.read    — read readiness and stats surfaces
  decision.write    — submit text or image review decisions
  decision.undo.own — undo decisions whose user_id resolves to the current user
  decision.undo.any — undo any decision regardless of authorship
  metric.add_missed — manually add a missed metric (POST /api/v2/missed-metric)
  ingest.run        — start, resume, or reextract ingest batches
  users.manage      — modify allowlist, roles, account status
  flags.manage      — modify rollout and emergency flags
  audit.read        — read audit-log surfaces

Role→permission map (spec §Permission Catalog table):

  admin    — all permissions
  reviewer — protected.read, readiness.read, decision.write, decision.undo.own
  viewer   — protected.read, readiness.read

Reference: docs/requirements/review-ui-authorization-spec.md §Permission Catalog
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Permission constants
# ---------------------------------------------------------------------------

#: Read protected pages: review UI, stats UI, ingest history UI.
PROTECTED_READ = "protected.read"

#: Read readiness and stats surfaces.
READINESS_READ = "readiness.read"

#: Submit text or image review decisions.
DECISION_WRITE = "decision.write"

#: Undo decisions whose user_id resolves to the current user (own decisions).
DECISION_UNDO_OWN = "decision.undo.own"

#: Undo any decision regardless of authorship.
DECISION_UNDO_ANY = "decision.undo.any"

#: Manually add a missed metric (POST /api/v2/missed-metric).
METRIC_ADD_MISSED = "metric.add_missed"

#: Start, resume, or reextract ingest batches.
INGEST_RUN = "ingest.run"

#: Modify allowlist, roles, account status.
USERS_MANAGE = "users.manage"

#: Modify rollout and emergency flags.
FLAGS_MANAGE = "flags.manage"

#: Read audit-log surfaces.
AUDIT_READ = "audit.read"

# Ordered tuple of all defined permissions — useful for validation and testing.
ALL_PERMISSIONS: tuple[str, ...] = (
    PROTECTED_READ,
    READINESS_READ,
    DECISION_WRITE,
    DECISION_UNDO_OWN,
    DECISION_UNDO_ANY,
    METRIC_ADD_MISSED,
    INGEST_RUN,
    USERS_MANAGE,
    FLAGS_MANAGE,
    AUDIT_READ,
)

# ---------------------------------------------------------------------------
# Role→permission map
# ---------------------------------------------------------------------------

#: Permissions granted to each role.
#: Keys are the ``auth_users.role`` values; values are frozensets of
#: permission strings from the constants above.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset(ALL_PERMISSIONS),
    "reviewer": frozenset(
        [
            PROTECTED_READ,
            READINESS_READ,
            DECISION_WRITE,
            DECISION_UNDO_OWN,
        ]
    ),
    "viewer": frozenset(
        [
            PROTECTED_READ,
            READINESS_READ,
        ]
    ),
}


def has_permission(role: str, permission: str) -> bool:
    """Return True if *role* grants *permission*.

    Args:
        role: Role string from ``auth_users.role`` (e.g. ``'admin'``).
        permission: Permission constant (e.g. ``DECISION_WRITE``).

    Returns:
        ``True`` if the role has the permission, ``False`` otherwise.
        Unknown roles always return ``False``.
    """
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
