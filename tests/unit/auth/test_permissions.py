"""
Unit tests for src.auth.permissions — permission catalog.

Verification checklist items from PR-A2 spec:
  - admin resolves to all permissions.
  - reviewer lacks decision.undo.any, metric.add_missed, ingest.run,
    users.manage, flags.manage, audit.read.
  - viewer lacks decision.write and decision.undo.own.
"""

from __future__ import annotations

import pytest

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

# ---------------------------------------------------------------------------
# Permission catalog: role coverage
# ---------------------------------------------------------------------------


class TestAdminPermissions:
    """admin role must grant every defined permission."""

    def test_admin_has_all_permissions(self) -> None:
        admin_perms = ROLE_PERMISSIONS["admin"]
        assert admin_perms == frozenset(ALL_PERMISSIONS)

    @pytest.mark.parametrize("perm", ALL_PERMISSIONS)
    def test_admin_has_permission(self, perm: str) -> None:
        assert has_permission("admin", perm) is True


class TestReviewerPermissions:
    """reviewer grants protected.read, readiness.read, decision.write,
    decision.undo.own — and nothing else."""

    ALLOWED = {PROTECTED_READ, READINESS_READ, DECISION_WRITE, DECISION_UNDO_OWN}
    DENIED = {
        DECISION_UNDO_ANY,
        METRIC_ADD_MISSED,
        INGEST_RUN,
        USERS_MANAGE,
        FLAGS_MANAGE,
        AUDIT_READ,
    }

    def test_reviewer_has_allowed_permissions(self) -> None:
        reviewer_perms = ROLE_PERMISSIONS["reviewer"]
        assert reviewer_perms == frozenset(self.ALLOWED)

    @pytest.mark.parametrize("perm", sorted(ALLOWED))
    def test_reviewer_allowed(self, perm: str) -> None:
        assert has_permission("reviewer", perm) is True

    @pytest.mark.parametrize("perm", sorted(DENIED))
    def test_reviewer_denied(self, perm: str) -> None:
        assert has_permission("reviewer", perm) is False


class TestViewerPermissions:
    """viewer grants only protected.read and readiness.read."""

    ALLOWED = {PROTECTED_READ, READINESS_READ}
    DENIED = {
        DECISION_WRITE,
        DECISION_UNDO_OWN,
        DECISION_UNDO_ANY,
        METRIC_ADD_MISSED,
        INGEST_RUN,
        USERS_MANAGE,
        FLAGS_MANAGE,
        AUDIT_READ,
    }

    def test_viewer_has_allowed_permissions(self) -> None:
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        assert viewer_perms == frozenset(self.ALLOWED)

    @pytest.mark.parametrize("perm", sorted(ALLOWED))
    def test_viewer_allowed(self, perm: str) -> None:
        assert has_permission("viewer", perm) is True

    @pytest.mark.parametrize("perm", sorted(DENIED))
    def test_viewer_denied(self, perm: str) -> None:
        assert has_permission("viewer", perm) is False


class TestUnknownRole:
    """Unknown roles always deny every permission."""

    @pytest.mark.parametrize("perm", ALL_PERMISSIONS)
    def test_unknown_role_denied(self, perm: str) -> None:
        assert has_permission("unknown_role", perm) is False

    def test_empty_role_denied(self) -> None:
        assert has_permission("", PROTECTED_READ) is False
