"""
Unit tests for src/auth/sessions.py.

All tests use monkeypatching to avoid real DB connections. The
psycopg.connect call is mocked via unittest.mock so no live database
or DATABASE_URL is required.

Coverage:
- _inactivity_hours / _absolute_days env-var parsing and fallbacks
- SessionUser dataclass construction
- create_session: happy path, returns UUID string, inserts correct SQL
- lookup_session: miss (no row), inactivity expiry, absolute lifetime
  expiry, disabled account, active account with sliding extend
- extend_session: empty session id no-op, normal UPDATE path
- revoke_session: empty session id no-op, DELETE path
- revoke_all_for_user: empty user id no-op, returns count
- _get_db_url: raises RuntimeError when DATABASE_URL unset
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.auth.sessions import (
    SessionUser,
    _absolute_days,
    _inactivity_hours,
    create_session,
    extend_session,
    lookup_session,
    revoke_all_for_user,
    revoke_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _make_row(
    *,
    session_id: str = "sid-1",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    user_id: str = "uid-1",
    normalized_email: str = "alice@example.com",
    display_name: str | None = "Alice",
    role: str = "reviewer",
    account_status: str = "active",
    now: datetime | None = None,
) -> dict:
    """Build a fake DB row matching the lookup_session SELECT columns."""
    return {
        "session_id": session_id,
        "session_created_at": created_at or (_NOW - timedelta(hours=1)),
        "session_expires_at": expires_at or (_NOW + timedelta(hours=23)),
        "user_id": user_id,
        "normalized_email": normalized_email,
        "display_name": display_name,
        "role": role,
        "account_status": account_status,
        "now": now or _NOW,
    }


def _mock_conn(row: dict | None = None, rowcount: int = 1):
    """Return a (context_manager, conn_mock, cursor_mock) triple.

    The context manager is what psycopg.connect(...) will return when used
    as ``with psycopg.connect(...) as conn:``.
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    # fetchall returns a list of dicts for revoke_all_for_user
    cursor.fetchall.return_value = [{"id": str(uuid.uuid4())} for _ in range(rowcount)]
    cursor.rowcount = rowcount

    conn = MagicMock()
    conn.execute.return_value = cursor
    conn.commit.return_value = None

    @contextmanager
    def _ctx(*args, **kwargs):
        yield conn

    return _ctx, conn, cursor


# ---------------------------------------------------------------------------
# _inactivity_hours
# ---------------------------------------------------------------------------


class TestInactivityHours:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_INACTIVITY_HOURS", raising=False)
        assert _inactivity_hours() == 24

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_INACTIVITY_HOURS", "48")
        assert _inactivity_hours() == 48

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_INACTIVITY_HOURS", "bad")
        assert _inactivity_hours() == 24

    def test_zero_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_INACTIVITY_HOURS", "0")
        assert _inactivity_hours() == 24

    def test_negative_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_INACTIVITY_HOURS", "-5")
        assert _inactivity_hours() == 24


# ---------------------------------------------------------------------------
# _absolute_days
# ---------------------------------------------------------------------------


class TestAbsoluteDays:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("AUTH_SESSION_ABSOLUTE_DAYS", raising=False)
        assert _absolute_days() == 30

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_ABSOLUTE_DAYS", "7")
        assert _absolute_days() == 7

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_ABSOLUTE_DAYS", "not-a-number")
        assert _absolute_days() == 30

    def test_zero_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_ABSOLUTE_DAYS", "0")
        assert _absolute_days() == 30


# ---------------------------------------------------------------------------
# SessionUser
# ---------------------------------------------------------------------------


class TestSessionUser:
    def test_immutable_dataclass(self):
        user = SessionUser(
            id="uid",
            email="u@example.com",
            display_name="U",
            role="admin",
            account_status="active",
        )
        assert user.id == "uid"
        assert user.email == "u@example.com"
        assert user.display_name == "U"
        assert user.role == "admin"
        assert user.account_status == "active"

    def test_display_name_optional(self):
        user = SessionUser(
            id="uid",
            email="u@example.com",
            display_name=None,
            role="viewer",
            account_status="active",
        )
        assert user.display_name is None

    def test_frozen(self):
        user = SessionUser(
            id="uid",
            email="u@example.com",
            display_name=None,
            role="viewer",
            account_status="active",
        )
        with pytest.raises((AttributeError, TypeError)):
            user.role = "admin"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _get_db_url / DATABASE_URL guard
# ---------------------------------------------------------------------------


class TestGetDbUrl:
    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        # create_session calls _get_db_url internally
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            create_session("uid-1")

    def test_passes_when_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        ctx, conn, cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            result = create_session("uid-1")
        assert result  # returns a UUID string


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    def setup_method(self):
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

    def teardown_method(self):
        os.environ.pop("DATABASE_URL", None)

    def test_returns_uuid_string(self):
        ctx, conn, _cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            sid = create_session("uid-abc")
        # Must be a valid UUID
        uuid.UUID(sid)

    def test_calls_insert(self):
        ctx, conn, _cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            create_session("uid-abc", user_agent="UA/1.0", ip_first_seen="1.2.3.4")
        # execute was called at least once (INSERT)
        assert conn.execute.called

    def test_calls_commit(self):
        ctx, conn, _cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            create_session("uid-abc")
        conn.commit.assert_called_once()

    def test_unique_ids(self):
        ctx, conn, _cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            sid1 = create_session("uid-abc")
            sid2 = create_session("uid-abc")
        assert sid1 != sid2

    def test_passes_user_agent_and_ip(self):
        ctx, conn, _cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            create_session("uid-abc", user_agent="TestAgent", ip_first_seen="10.0.0.1")
        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert "TestAgent" in params
        assert "10.0.0.1" in params


# ---------------------------------------------------------------------------
# lookup_session
# ---------------------------------------------------------------------------


class TestLookupSession:
    def setup_method(self):
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

    def teardown_method(self):
        os.environ.pop("DATABASE_URL", None)

    def test_empty_session_id_returns_none(self):
        assert lookup_session("") is None

    def test_missing_row_returns_none(self):
        ctx, conn, _cursor = _mock_conn(row=None)
        with patch("psycopg.connect", ctx):
            result = lookup_session("nonexistent")
        assert result is None

    def test_active_session_returns_session_user(self):
        row = _make_row()
        ctx, conn, _cursor = _mock_conn(row=row)
        with patch("psycopg.connect", ctx):
            result = lookup_session("valid-session")
        assert isinstance(result, SessionUser)
        assert result.email == "alice@example.com"
        assert result.role == "reviewer"
        assert result.id == "uid-1"

    def test_extends_sliding_window_on_success(self):
        row = _make_row()
        ctx, conn, _cursor = _mock_conn(row=row)
        with patch("psycopg.connect", ctx):
            result = lookup_session("valid-session")
        assert result is not None
        # Should have issued two execute calls: SELECT and UPDATE
        assert conn.execute.call_count == 2
        conn.commit.assert_called_once()

    def test_inactivity_expiry_returns_none(self):
        # expires_at is in the past
        row = _make_row(expires_at=_NOW - timedelta(seconds=1))
        ctx, conn, _cursor = _mock_conn(row=row)
        with patch("psycopg.connect", ctx):
            result = lookup_session("expired-session")
        assert result is None

    def test_absolute_lifetime_returns_none(self, monkeypatch):
        monkeypatch.setenv("AUTH_SESSION_ABSOLUTE_DAYS", "30")
        # created_at is 31 days ago — past absolute cap
        old_created = _NOW - timedelta(days=31)
        row = _make_row(
            created_at=old_created,
            expires_at=_NOW + timedelta(hours=1),  # inactivity still valid
        )
        ctx, conn, _cursor = _mock_conn(row=row)
        with patch("psycopg.connect", ctx):
            result = lookup_session("old-session")
        assert result is None

    def test_disabled_account_returns_none(self):
        row = _make_row(account_status="disabled")
        ctx, conn, _cursor = _mock_conn(row=row)
        with patch("psycopg.connect", ctx):
            result = lookup_session("disabled-session")
        assert result is None

    def test_db_exception_returns_none(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        def _bad_connect(*args, **kwargs):
            raise RuntimeError("DB down")

        with patch("psycopg.connect", _bad_connect):
            result = lookup_session("any-session")
        assert result is None

    def test_naive_datetimes_get_utc(self):
        """Naive datetimes from Postgres are coerced to UTC without error."""
        now_naive = _NOW.replace(tzinfo=None)
        row = _make_row(
            created_at=(_NOW - timedelta(hours=1)).replace(tzinfo=None),
            expires_at=(_NOW + timedelta(hours=23)).replace(tzinfo=None),
            now=now_naive,
        )
        ctx, conn, _cursor = _mock_conn(row=row)
        with patch("psycopg.connect", ctx):
            result = lookup_session("valid-session")
        assert isinstance(result, SessionUser)


# ---------------------------------------------------------------------------
# extend_session
# ---------------------------------------------------------------------------


class TestExtendSession:
    def setup_method(self):
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

    def teardown_method(self):
        os.environ.pop("DATABASE_URL", None)

    def test_empty_session_id_is_noop(self):
        with patch("psycopg.connect") as mock_connect:
            extend_session("")
        mock_connect.assert_not_called()

    def test_issues_update(self):
        ctx, conn, _cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            extend_session("some-session-id")
        assert conn.execute.called
        conn.commit.assert_called_once()

    def test_db_exception_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        def _bad_connect(*args, **kwargs):
            raise RuntimeError("DB down")

        # Should not propagate the exception
        with patch("psycopg.connect", _bad_connect):
            extend_session("some-session")  # no raise


# ---------------------------------------------------------------------------
# revoke_session
# ---------------------------------------------------------------------------


class TestRevokeSession:
    def setup_method(self):
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

    def teardown_method(self):
        os.environ.pop("DATABASE_URL", None)

    def test_empty_session_id_is_noop(self):
        with patch("psycopg.connect") as mock_connect:
            revoke_session("")
        mock_connect.assert_not_called()

    def test_issues_delete(self):
        ctx, conn, _cursor = _mock_conn()
        with patch("psycopg.connect", ctx):
            revoke_session("some-session-id")
        assert conn.execute.called
        conn.commit.assert_called_once()

    def test_db_exception_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        def _bad_connect(*args, **kwargs):
            raise RuntimeError("DB down")

        with patch("psycopg.connect", _bad_connect):
            revoke_session("some-session")  # no raise


# ---------------------------------------------------------------------------
# revoke_all_for_user
# ---------------------------------------------------------------------------


class TestRevokeAllForUser:
    def setup_method(self):
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

    def teardown_method(self):
        os.environ.pop("DATABASE_URL", None)

    def test_empty_user_id_returns_zero(self):
        with patch("psycopg.connect") as mock_connect:
            count = revoke_all_for_user("")
        mock_connect.assert_not_called()
        assert count == 0

    def test_returns_count_of_revoked(self):
        # 3 sessions to revoke
        ctx, conn, _cursor = _mock_conn(rowcount=3)
        _cursor.fetchall.return_value = [{"id": str(uuid.uuid4())} for _ in range(3)]
        with patch("psycopg.connect", ctx):
            count = revoke_all_for_user("uid-abc")
        assert count == 3

    def test_returns_zero_when_no_sessions(self):
        ctx, conn, _cursor = _mock_conn(rowcount=0)
        _cursor.fetchall.return_value = []
        with patch("psycopg.connect", ctx):
            count = revoke_all_for_user("uid-abc")
        assert count == 0

    def test_db_exception_returns_zero(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        def _bad_connect(*args, **kwargs):
            raise RuntimeError("DB down")

        with patch("psycopg.connect", _bad_connect):
            count = revoke_all_for_user("uid-abc")
        assert count == 0
