"""
Integration tests for the OAuth login flow (PR-A5).

Drives the ``/auth/login`` → ``/auth/callback`` flow end-to-end through a
Flask test client, with stubs for Google's token-exchange and ID-token
validation so no real network calls happen.

Each test:
  1. Truncates auth tables.
  2. Seeds an ``auth_access_entries`` row when the test is exercising an
     allowlisted user.
  3. Stubs the per-flow ``state`` / ``nonce`` so the callback URL can be
     constructed deterministically.
  4. Calls ``/auth/login`` (which stashes the per-flow values in the Flask
     framework session cookie the test client carries).
  5. Calls ``/auth/callback`` with controlled query args and stubbed
     Google response.
  6. Asserts on the redirect target, the ``auth_users`` row, the
     ``auth_sessions`` row, and the ``admin_audit_log`` row.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from src.auth.oidc_validate import OidcValidationError

from .conftest import _truncate_auth_tables

FIXED_STATE = "test-fixed-state"
FIXED_NONCE = "stash-me-test-nonce"
FIXED_VERIFIER = "test-fixed-verifier"
FIXED_CHALLENGE = "test-fixed-challenge"


@pytest.fixture
def stub_per_flow_values(monkeypatch):
    """Pin state/nonce/PKCE so callback URLs can be built deterministically.

    Patches the names imported into ``src.web.routes.auth`` (not the
    originals in ``src.auth.oauth``) — that's where the route code looks
    them up at call time.
    """
    monkeypatch.setattr("src.web.routes.auth.generate_state", lambda: FIXED_STATE)
    monkeypatch.setattr("src.web.routes.auth.generate_nonce", lambda: FIXED_NONCE)
    monkeypatch.setattr(
        "src.web.routes.auth.generate_pkce_pair",
        lambda: (FIXED_VERIFIER, FIXED_CHALLENGE),
    )


@pytest.fixture
def auth_db(test_db_adapter):
    _truncate_auth_tables(test_db_adapter)
    yield test_db_adapter
    _truncate_auth_tables(test_db_adapter)


def _seed_access_entry(
    db,
    *,
    email: str = "alice@example.com",
    role: str = "reviewer",
    status: str = "approved",
) -> None:
    db.execute(
        """
        INSERT INTO auth_access_entries (normalized_email, intended_role, status)
        VALUES (%(ne)s, %(role)s, %(status)s)
        ON CONFLICT (normalized_email) DO UPDATE
        SET intended_role = EXCLUDED.intended_role,
            status = EXCLUDED.status
        """,
        {"ne": email, "role": role, "status": status},
    )


def _audit_rows(db, action_type: str | None = None) -> list[dict]:
    if action_type:
        return db.query(
            """
            SELECT actor_user_id::text AS actor_user_id, actor_email,
                   action_type, target_entity, success, error
            FROM admin_audit_log
            WHERE action_type = %(at)s
            ORDER BY id ASC
            """,
            {"at": action_type},
        )
    return db.query(
        """
        SELECT actor_user_id::text AS actor_user_id, actor_email,
               action_type, target_entity, success, error
        FROM admin_audit_log
        ORDER BY id ASC
        """
    )


def _start_login(oauth_client) -> None:
    """Drive the /auth/login redirect so the framework session is populated."""
    response = oauth_client.get("/auth/login?next=/v2/review/")
    assert response.status_code == 302


def _callback(oauth_client, *, state: str = FIXED_STATE, code: str = "fake-code"):
    return oauth_client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_successful_login_creates_user_and_session(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer")
        stub_google_oauth(claims=good_claims)

        _start_login(oauth_client)
        response = _callback(oauth_client)

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/v2/review/")

        # auth_users row created.
        users = auth_db.query(
            "SELECT id::text AS id, normalized_email, role, account_status, "
            "google_sub, display_name, first_login_at, last_login_at "
            "FROM auth_users"
        )
        assert len(users) == 1
        u = users[0]
        assert u["normalized_email"] == "alice@example.com"
        assert u["role"] == "reviewer"
        assert u["account_status"] == "active"
        assert u["google_sub"] == "google-sub-12345"
        assert u["display_name"] == "Alice Example"
        assert u["first_login_at"] is not None
        assert u["last_login_at"] is not None

        # auth_sessions row created.
        sessions = auth_db.query("SELECT user_id::text AS user_id FROM auth_sessions")
        assert len(sessions) == 1
        assert sessions[0]["user_id"] == u["id"]

        # admin_audit_log row written with success.
        audit = _audit_rows(auth_db, action_type="auth.login")
        assert len(audit) == 1
        assert audit[0]["success"] is True
        assert audit[0]["error"] is None
        assert audit[0]["actor_email"] == "alice@example.com"
        assert audit[0]["target_entity"] == "alice@example.com"

    def test_login_uppercase_email_normalises(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        _seed_access_entry(auth_db, email="alice@example.com", role="admin")
        good_claims["email"] = "Alice@EXAMPLE.com"  # mixed-case from Google
        stub_google_oauth(claims=good_claims)

        _start_login(oauth_client)
        response = _callback(oauth_client)

        assert response.status_code == 302
        users = auth_db.query("SELECT normalized_email, role FROM auth_users")
        assert users[0]["normalized_email"] == "alice@example.com"
        assert users[0]["role"] == "admin"

    def test_login_redirects_to_default_when_next_invalid(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer")
        stub_google_oauth(claims=good_claims)

        # Tamper with next via a subsequent /auth/login that injects a bad value.
        oauth_client.get("/auth/login?next=//evil.com")
        response = _callback(oauth_client)
        assert response.headers["Location"].endswith("/v2/review/")


# ---------------------------------------------------------------------------
# Denials — one per audit reason
# ---------------------------------------------------------------------------


class TestDenials:
    def test_state_mismatch(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer")
        stub_google_oauth(claims=good_claims)

        _start_login(oauth_client)
        response = _callback(oauth_client, state="WRONG-STATE")

        assert response.status_code == 302
        assert "/auth/denied" in response.headers["Location"]
        assert "oauth_state_mismatch" in response.headers["Location"]

        # No auth_users row created.
        users = auth_db.query("SELECT 1 FROM auth_users")
        assert users == []
        audit = _audit_rows(auth_db, action_type="auth.login_denied")
        assert len(audit) == 1
        assert audit[0]["error"] == "oauth_state_mismatch"

    def test_email_verified_false(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer")
        stub_google_oauth(raise_validate=OidcValidationError("email_unverified", "stub"))

        _start_login(oauth_client)
        response = _callback(oauth_client)

        assert "email_unverified" in response.headers["Location"]
        users = auth_db.query("SELECT 1 FROM auth_users")
        assert users == []
        audit = _audit_rows(auth_db, action_type="auth.login_denied")
        assert audit[0]["error"] == "email_unverified"

    def test_invalid_id_token(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
    ):
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer")
        stub_google_oauth(raise_validate=OidcValidationError("oauth_id_token_invalid", "expired"))

        _start_login(oauth_client)
        response = _callback(oauth_client)

        assert "oauth_id_token_invalid" in response.headers["Location"]
        audit = _audit_rows(auth_db, action_type="auth.login_denied")
        assert audit[0]["error"] == "oauth_id_token_invalid"

    def test_not_allowlisted(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        # No auth_access_entries row → allowlist miss.
        stub_google_oauth(claims=good_claims)

        _start_login(oauth_client)
        response = _callback(oauth_client)

        assert "not_allowlisted" in response.headers["Location"]
        users = auth_db.query("SELECT 1 FROM auth_users")
        assert users == []
        audit = _audit_rows(auth_db, action_type="auth.login_denied")
        assert audit[0]["error"] == "not_allowlisted"
        assert audit[0]["actor_email"] == "alice@example.com"

    def test_pending_allowlist_entry_does_not_count(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        # An allowlist row with status='pending' is NOT a match.
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer", status="pending")
        stub_google_oauth(claims=good_claims)

        _start_login(oauth_client)
        response = _callback(oauth_client)

        assert "not_allowlisted" in response.headers["Location"]

    def test_disabled_user_denied(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer")
        # Pre-create a disabled auth_users row so the upsert keeps the disabled status.
        auth_db.execute(
            """
            INSERT INTO auth_users (
                normalized_email, role, account_status, disabled_at
            ) VALUES (
                'alice@example.com', 'reviewer', 'disabled', NOW()
            )
            """
        )
        stub_google_oauth(claims=good_claims)

        # Capture last_login_at before the denied attempt (NULL on fresh row).
        pre_last_login = auth_db.query(
            "SELECT last_login_at FROM auth_users WHERE normalized_email = 'alice@example.com'"
        )[0]["last_login_at"]

        _start_login(oauth_client)
        response = _callback(oauth_client)

        assert "account_disabled" in response.headers["Location"]
        # account_status still disabled; upsert must not have run.
        rows = auth_db.query(
            "SELECT account_status, last_login_at FROM auth_users WHERE normalized_email = 'alice@example.com'"
        )
        assert rows[0]["account_status"] == "disabled"
        # last_login_at must not be bumped by a denied attempt (Fix 2).
        assert rows[0]["last_login_at"] == pre_last_login
        # No auth_sessions row created.
        sessions = auth_db.query("SELECT 1 FROM auth_sessions")
        assert sessions == []
        audit = _audit_rows(auth_db, action_type="auth.login_denied")
        assert audit[0]["error"] == "account_disabled"
        assert audit[0]["target_entity"] == "alice@example.com"

    def test_callback_without_code_denied(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
    ):
        _start_login(oauth_client)
        response = oauth_client.get(
            f"/auth/callback?state={FIXED_STATE}",
            follow_redirects=False,
        )
        assert "oauth_callback_error" in response.headers["Location"]
        audit = _audit_rows(auth_db, action_type="auth.login_denied")
        assert audit[0]["error"] == "oauth_callback_error"


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestLogout:
    def test_logout_revokes_session_and_audits(
        self,
        oauth_client,
        auth_db,
        stub_per_flow_values,
        stub_google_oauth,
        good_claims,
    ):
        # Log in first.
        _seed_access_entry(auth_db, email="alice@example.com", role="reviewer")
        stub_google_oauth(claims=good_claims)
        _start_login(oauth_client)
        _callback(oauth_client)
        sessions_before = auth_db.query("SELECT 1 FROM auth_sessions")
        assert len(sessions_before) == 1

        # Logout.
        response = oauth_client.post("/auth/logout")
        assert response.status_code == 302

        # Session row gone.
        sessions_after = auth_db.query("SELECT 1 FROM auth_sessions")
        assert sessions_after == []

        # Audit row.
        audit = _audit_rows(auth_db, action_type="auth.logout")
        assert len(audit) == 1
        assert audit[0]["success"] is True


# ---------------------------------------------------------------------------
# /auth/login URL shape (sanity check on the redirect target)
# ---------------------------------------------------------------------------


class TestLoginRedirect:
    def test_login_redirects_to_google_with_pkce(self, oauth_client, stub_per_flow_values):
        response = oauth_client.get("/auth/login?next=/v2/review/")
        assert response.status_code == 302

        target = urlparse(response.headers["Location"])
        assert target.netloc == "accounts.google.com"
        params = parse_qs(target.query)
        assert params["client_id"] == ["test-client-id"]
        assert params["state"] == [FIXED_STATE]
        assert params["nonce"] == [FIXED_NONCE]
        assert params["code_challenge"] == [FIXED_CHALLENGE]
        assert params["code_challenge_method"] == ["S256"]
        assert params["response_type"] == ["code"]
        assert params["scope"] == ["openid email profile"]
