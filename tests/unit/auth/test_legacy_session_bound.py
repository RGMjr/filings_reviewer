"""
Unit tests for the 4-hour legacy-session bound in src.auth.load_user.

Spec §Cutover Rules → Existing Open Pages at Enforcement Time:
when auth_enforcement_enabled flips to true, sessions created BEFORE the
flip are forcibly invalidated 4 hours after the flip (regardless of
activity). Implemented in `_apply_legacy_session_bound`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from src.auth.load_user import _apply_legacy_session_bound
from src.auth.sessions import SessionUser


def _user() -> SessionUser:
    return SessionUser(
        id="00000000-0000-0000-0000-000000000001",
        email="rgm@example.com",
        display_name="RGM",
        role="reviewer",
        account_status="active",
    )


SESSION_ID = "session-abc123"


class TestLegacySessionBound:
    def test_flag_off_returns_user_unchanged(self):
        """When enforcement_started_at()=None (flag off), bound never applies."""
        user = _user()
        with patch(
            "src.auth.load_user.enforcement_started_at",
            return_value=None,
        ):
            result = _apply_legacy_session_bound(user, SESSION_ID)
        assert result is user

    def test_within_4h_grace_window_returns_user(self):
        """Even if session is legacy, within-4h-of-flip → still valid."""
        user = _user()
        flip_at = datetime.now(tz=UTC) - timedelta(hours=2)
        with patch(
            "src.auth.load_user.enforcement_started_at",
            return_value=flip_at,
        ):
            result = _apply_legacy_session_bound(user, SESSION_ID)
        assert result is user

    def test_legacy_session_after_4h_returns_none(self):
        """Session created BEFORE flip + >4h elapsed → None (rejected)."""
        user = _user()
        flip_at = datetime.now(tz=UTC) - timedelta(hours=5)
        session_created = flip_at - timedelta(minutes=30)

        # Mock the DB lookup of created_at.
        fake_row = {"created_at": session_created}

        class FakeCursor:
            def fetchone(self):
                return fake_row

        class FakeConn:
            def execute(self, *args, **kwargs):
                return FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with (
            patch(
                "src.auth.load_user.enforcement_started_at",
                return_value=flip_at,
            ),
            patch("psycopg.connect", return_value=FakeConn()),
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://x"}),
        ):
            result = _apply_legacy_session_bound(user, SESSION_ID)
        assert result is None

    def test_session_created_after_flip_returns_user(self):
        """Session created AFTER the flip (fresh session) — bound never applies."""
        user = _user()
        flip_at = datetime.now(tz=UTC) - timedelta(hours=5)
        session_created = flip_at + timedelta(minutes=30)
        fake_row = {"created_at": session_created}

        class FakeCursor:
            def fetchone(self):
                return fake_row

        class FakeConn:
            def execute(self, *args, **kwargs):
                return FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with (
            patch(
                "src.auth.load_user.enforcement_started_at",
                return_value=flip_at,
            ),
            patch("psycopg.connect", return_value=FakeConn()),
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://x"}),
        ):
            result = _apply_legacy_session_bound(user, SESSION_ID)
        assert result is user

    def test_db_lookup_failure_fails_open(self):
        """A DB hiccup on the created_at fetch → user kept (don't lock people out)."""
        user = _user()
        flip_at = datetime.now(tz=UTC) - timedelta(hours=5)
        with (
            patch(
                "src.auth.load_user.enforcement_started_at",
                return_value=flip_at,
            ),
            patch("psycopg.connect", side_effect=RuntimeError("DB down")),
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://x"}),
        ):
            result = _apply_legacy_session_bound(user, SESSION_ID)
        assert result is user
