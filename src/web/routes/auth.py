"""
Google OAuth login routes (PR-A5).

Blueprint registered conditionally on the ``google_login_enabled`` feature
flag — when off, none of these routes exist (404 from Flask). When on,
unauthenticated users sign in at ``/auth/login`` and Google redirects to
``/auth/callback`` to complete the flow.

Two distinct cookies are involved here, do not conflate:

  - **Flask framework session** (``flask.session``) — short-lived, signed
    by ``app.config['SECRET_KEY']``. We use it only to stash ``state``,
    ``nonce``, ``code_verifier``, and ``next`` between ``/auth/login`` and
    ``/auth/callback``.
  - **auth_session cookie** (handled by ``src.auth.cookies``) — long-lived,
    holds an opaque ``auth_sessions.id``. Set on the response from
    ``/auth/callback`` after a successful login.

After this PR ships, route-level enforcement (the ``require()`` decorator
from PR-A2) is still in shadow mode — these routes are the only ones that
actually consume the new auth surface. Stage C migrates the existing routes.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Any

from flask import (
    Blueprint,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from src.auth.cookies import clear_session_cookie, set_session_cookie
from src.auth.oauth import (
    OAuthExchangeError,
    build_authorization_url,
    exchange_code_for_tokens,
    generate_nonce,
    generate_pkce_pair,
    generate_state,
)
from src.auth.oidc_validate import OidcValidationError, validate_id_token
from src.auth.sessions import revoke_session

logger = logging.getLogger(__name__)

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
    template_folder="../templates/auth",
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Allowed prefixes for the post-login redirect target. Anything else falls
# back to the default. Keep this short — every entry is a public surface
# the OAuth flow can deliver users to.
_ALLOWED_NEXT_PREFIXES: tuple[str, ...] = (
    "/v2/review/",
    "/ingest/",
    "/v2/review",  # bare prefix without trailing slash (single page redirect)
    "/ingest",
)

DEFAULT_NEXT = "/v2/review/"

# Flask-session keys for the per-flow OAuth values (cleared on callback).
_SESS_STATE = "oauth_state"
_SESS_NONCE = "oauth_nonce"
_SESS_VERIFIER = "oauth_code_verifier"
_SESS_NEXT = "oauth_next"

# Audit action_type values — keep in sync with PR-A8 readiness report consumers.
_ACTION_LOGIN = "auth.login"
_ACTION_LOGOUT = "auth.logout"
_ACTION_LOGIN_DENIED = "auth.login_denied"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_email(email: str) -> str:
    """Lowercase + strip. Must match ``scripts/seed_auth_users.normalize_email``.

    Per spec §Access Model: "lowercase + Unicode NFC, no Gmail dot-or-plus
    alias normalization." We rely on ``str.lower()`` (which preserves NFC for
    ASCII inputs) and explicit ``.strip()``.
    """
    return email.lower().strip()


def _validate_next(raw: str | None) -> str:
    """Return a safe redirect target derived from *raw*.

    Per spec §UI Identity → redirect-target rules:

    - Must start with a single ``/`` (not ``//``, which is protocol-relative).
    - Must not contain ``\\`` (backslash variants used to bypass naive validators).
    - Must not contain ``:`` before the first ``/`` (rejects ``javascript:`` etc.).
    - After URL-decoding, must resolve to a known route prefix.

    Anything that fails returns ``DEFAULT_NEXT``. Logs failures so the audit
    trail can surface bypass attempts.
    """
    if not raw:
        return DEFAULT_NEXT

    # URL-decode first, per the spec's "decode then check" rule. This catches
    # %2F%2Fevil.com which would otherwise sneak past the literal-prefix check.
    decoded = urllib.parse.unquote(raw)

    if "\\" in decoded:
        logger.warning("auth: rejecting next-target with backslash: %r", raw)
        return DEFAULT_NEXT

    # Reject anything with a scheme-like ``:`` before the first ``/``.
    first_slash = decoded.find("/")
    if first_slash == -1:
        logger.warning("auth: rejecting next-target without leading slash: %r", raw)
        return DEFAULT_NEXT
    if ":" in decoded[:first_slash]:
        logger.warning("auth: rejecting next-target with scheme prefix: %r", raw)
        return DEFAULT_NEXT

    # Must start with exactly one slash (not //, not anything else).
    if not decoded.startswith("/") or decoded.startswith("//"):
        logger.warning("auth: rejecting next-target with bad leading slash: %r", raw)
        return DEFAULT_NEXT

    # Normalise path traversal — split, drop ``..`` and empty segments, rejoin.
    # If the normalised path doesn't match the original (modulo query string),
    # it was trying to escape; reject.
    path_only, _, query = decoded.partition("?")
    parts: list[str] = []
    for segment in path_only.split("/"):
        if segment == "..":
            logger.warning("auth: rejecting next-target with traversal: %r", raw)
            return DEFAULT_NEXT
        # Empty segments are fine for // detection (already handled above) and
        # for a trailing slash. ``.`` segments are harmless but stripping them
        # changes the path; just leave them in place.
        parts.append(segment)
    normalised = "/".join(parts)
    if query:
        normalised = f"{normalised}?{query}"

    # Must match a known prefix.
    for prefix in _ALLOWED_NEXT_PREFIXES:
        if (
            normalised == prefix
            or normalised.startswith(prefix + "?")
            or normalised.startswith(prefix + "/")
        ):
            return normalised
        # Allow a bare prefix-equal match where the prefix has a trailing slash
        # and the normalised path drops it.
        if prefix.endswith("/") and normalised == prefix.rstrip("/"):
            return prefix

    logger.warning("auth: rejecting next-target outside known prefixes: %r", raw)
    return DEFAULT_NEXT


def _audit_login(
    *,
    action_type: str,
    success: bool,
    error: str | None,
    actor_user_id: str | None = None,
    actor_email: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> None:
    """Append a row to ``admin_audit_log``.

    Local helper rather than reusing ``src/web/middleware.py::insert_audit_log_entry``
    because that one writes to the V2-pipeline ``v2_audit_log`` table, which
    is a different concern (request-timing/IP audit, not auth events).
    """
    from src.web.app import get_db

    # Email first per seed-script precedent; falls back to user_id for paths
    # where the email is not yet known (state mismatch, pre-token-validation errors).
    target_entity = actor_email or actor_user_id

    try:
        db = get_db()
        db.execute(
            """
            INSERT INTO admin_audit_log (
                actor_user_id,
                actor_email,
                action_type,
                target_entity,
                before_state,
                after_state,
                success,
                error
            ) VALUES (
                %(actor_user_id)s,
                %(actor_email)s,
                %(action_type)s,
                %(target_entity)s,
                %(before_state)s::jsonb,
                %(after_state)s::jsonb,
                %(success)s,
                %(error)s
            )
            """,
            {
                "actor_user_id": actor_user_id,
                "actor_email": actor_email,
                "action_type": action_type,
                "target_entity": target_entity,
                "before_state": json.dumps(before_state) if before_state else None,
                "after_state": json.dumps(after_state) if after_state else None,
                "success": success,
                "error": error,
            },
        )
    except Exception as exc:
        # Audit-log failures must NOT break the auth flow. Log loudly and
        # continue — the request itself will still succeed/deny correctly.
        logger.error(
            "Failed to write admin_audit_log row (action=%s, error=%s): %s",
            action_type,
            error,
            exc,
        )


def _oauth_config() -> tuple[str, str, str]:
    """Return ``(client_id, client_secret, redirect_uri)`` from env.

    Read at request time (not import time) so:
      - tests can monkeypatch via ``monkeypatch.setenv``;
      - operator changes via Render env-group rollouts take effect on the
        next request after a service restart, with no code change.

    Raises:
        RuntimeError: if any of the three vars is missing — the route handler
            converts this into a 500 with an audit row.
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if not (client_id and client_secret and redirect_uri):
        raise RuntimeError(
            "Google OAuth env vars missing — set GOOGLE_OAUTH_CLIENT_ID, "
            "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REDIRECT_URI."
        )
    return client_id, client_secret, redirect_uri


def _lookup_access_entry(normalized_email: str) -> dict | None:
    """Return the ``auth_access_entries`` row for *normalized_email*, or None.

    Only ``status='approved'`` entries count as "allowlisted". Pending /
    revoked entries are treated as a miss.
    """
    from src.web.app import get_db

    db = get_db()
    rows = db.query(
        """
        SELECT id, normalized_email, intended_role, status
        FROM auth_access_entries
        WHERE normalized_email = %(ne)s
          AND status = 'approved'
        LIMIT 1
        """,
        {"ne": normalized_email},
    )
    return rows[0] if rows else None


def _upsert_user(
    *,
    normalized_email: str,
    google_sub: str,
    display_name: str | None,
    intended_role: str,
) -> dict:
    """Insert / update the ``auth_users`` row for the logged-in user.

    Conflict key is ``normalized_email`` (NOT ``google_sub``) — seeded rows
    have ``google_sub=NULL`` until first login, and using ``google_sub`` as
    the conflict key would silently insert a duplicate row for them.

    On UPDATE we set ``google_sub`` (only if it was NULL — the seed inserts
    a real value the first time), refresh ``display_name``, bump
    ``last_login_at``, and set ``first_login_at`` only if it was NULL.

    Returns the resulting row (post-upsert).
    """
    from src.web.app import get_db

    db = get_db()
    rows = db.execute(
        """
        INSERT INTO auth_users (
            normalized_email,
            google_sub,
            display_name,
            role,
            account_status,
            first_login_at,
            last_login_at
        ) VALUES (
            %(ne)s,
            %(sub)s,
            %(name)s,
            %(role)s,
            'active',
            NOW(),
            NOW()
        )
        ON CONFLICT (normalized_email) DO UPDATE
        SET google_sub      = COALESCE(auth_users.google_sub, EXCLUDED.google_sub),
            display_name    = COALESCE(EXCLUDED.display_name, auth_users.display_name),
            last_login_at   = NOW(),
            first_login_at  = COALESCE(auth_users.first_login_at, NOW()),
            updated_at      = NOW()
        RETURNING
            id::text AS id,
            normalized_email,
            google_sub,
            display_name,
            role,
            account_status,
            first_login_at,
            last_login_at,
            created_at,
            updated_at
        """,
        {
            "ne": normalized_email,
            "sub": google_sub,
            "name": display_name,
            "role": intended_role,
        },
        fetch=True,
    )
    if not rows:
        raise RuntimeError("auth_users upsert returned no row — invariant violated")
    return rows[0]


def _user_snapshot(row: dict | None) -> dict | None:
    """Convert a DB row to a JSON-serialisable dict for audit log states.

    Drops timestamp / UUID types that don't serialise cleanly. Returns None
    when the input is None so audit calls can pass it through unchanged.
    """
    if row is None:
        return None
    snap: dict[str, Any] = {}
    for k, v in row.items():
        if v is None:
            snap[k] = None
        elif hasattr(v, "isoformat"):
            snap[k] = v.isoformat()
        else:
            snap[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v
    return snap


def _redirect_to_denied(reason: str):
    """Helper: redirect to ``/auth/denied?reason=<reason>``."""
    return redirect(url_for("auth.denied", reason=reason))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@auth_bp.route("/login", methods=["GET"])
def login():
    """Start the OAuth flow.

    Generates per-flow state/nonce/PKCE, stashes them in the Flask framework
    session, and redirects to Google's authorization endpoint.

    Query parameters:
        next: Optional return-to-origin path. Validated by ``_validate_next``.
    """
    try:
        client_id, _, redirect_uri = _oauth_config()
    except RuntimeError as exc:
        logger.error("OAuth login configuration error: %s", exc)
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error="oauth_callback_error",
        )
        return _redirect_to_denied("oauth_callback_error")

    state = generate_state()
    nonce = generate_nonce()
    code_verifier, code_challenge = generate_pkce_pair()

    session[_SESS_STATE] = state
    session[_SESS_NONCE] = nonce
    session[_SESS_VERIFIER] = code_verifier
    session[_SESS_NEXT] = _validate_next(request.args.get("next"))

    auth_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
    )
    return redirect(auth_url)


@auth_bp.route("/callback", methods=["GET"])
def callback():
    """Handle the OAuth callback from Google.

    Verifies state, exchanges code, validates the ID token, runs allowlist
    + account-status checks, upserts ``auth_users``, creates an
    ``auth_sessions`` row, sets the session cookie, audits, and redirects.
    """
    # Pop per-flow values up front — even if we deny, we don't want stale
    # state/nonce/verifier sticking around for a subsequent attempt.
    expected_state = session.pop(_SESS_STATE, None)
    expected_nonce = session.pop(_SESS_NONCE, None)
    code_verifier = session.pop(_SESS_VERIFIER, None)
    next_target = session.pop(_SESS_NEXT, DEFAULT_NEXT)

    # State validation — must match what we stashed at /auth/login.
    received_state = request.args.get("state", "")
    if not expected_state or received_state != expected_state:
        logger.warning("OAuth callback: state mismatch")
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error="oauth_state_mismatch",
        )
        return _redirect_to_denied("oauth_state_mismatch")

    code = request.args.get("code", "")
    if not code or not code_verifier:
        # Either Google didn't return a code (user cancelled, etc.) or we
        # lost the verifier. Same audit reason for both.
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error="oauth_callback_error",
        )
        return _redirect_to_denied("oauth_callback_error")

    try:
        client_id, client_secret, redirect_uri = _oauth_config()
    except RuntimeError:
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error="oauth_callback_error",
        )
        return _redirect_to_denied("oauth_callback_error")

    # Token exchange.
    try:
        tokens = exchange_code_for_tokens(
            code=code,
            code_verifier=code_verifier,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    except OAuthExchangeError as exc:
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error=exc.reason,
        )
        return _redirect_to_denied(exc.reason)

    # ID-token validation (signature, aud, iss, exp, nonce, email_verified).
    try:
        if expected_nonce is None:
            raise OidcValidationError(
                "oauth_id_token_invalid",
                "expected_nonce missing from session",
            )
        claims = validate_id_token(
            tokens["id_token"],
            client_id=client_id,
            expected_nonce=expected_nonce,
        )
    except OidcValidationError as exc:
        # We don't try to extract the email from a failed ID token — the
        # audit row's ``error`` column already pinpoints the failure mode,
        # and pulling unverified claims out of an unsigned JWT requires an
        # extra dependency (``PyJWT``) that the rest of the project doesn't
        # use. Leave ``actor_email`` NULL.
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error=exc.reason,
        )
        return _redirect_to_denied(exc.reason)

    google_sub = claims.get("sub")
    raw_email = claims.get("email", "")
    display_name = claims.get("name")
    if not google_sub or not raw_email:
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error="oauth_id_token_invalid",
        )
        return _redirect_to_denied("oauth_id_token_invalid")

    normalized_email = _normalize_email(raw_email)

    # Allowlist check. ``not_allowlisted`` and ``email_unverified`` SHARE
    # user-visible wording (no leak about which accounts are allowlisted),
    # but the audit row records the precise reason.
    access_entry = _lookup_access_entry(normalized_email)
    if access_entry is None:
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error="not_allowlisted",
            actor_email=normalized_email,
        )
        return _redirect_to_denied("not_allowlisted")

    # Capture the pre-upsert row for the audit log (NULL on first login).
    from src.web.app import get_db

    db = get_db()
    pre_rows = db.query(
        """
        SELECT id::text AS id, normalized_email, google_sub, display_name,
               role, account_status, first_login_at, last_login_at,
               created_at, updated_at
        FROM auth_users
        WHERE normalized_email = %(ne)s
        LIMIT 1
        """,
        {"ne": normalized_email},
    )
    pre_row = pre_rows[0] if pre_rows else None

    # Account-status check happens BEFORE upsert so a disabled user's
    # last_login_at is not silently bumped on every denied attempt.
    # Only applies when the row already exists (pre_row is not None); first-time
    # logins by someone not yet in auth_users cannot be disabled yet.
    if pre_row is not None and pre_row["account_status"] != "active":
        _audit_login(
            action_type=_ACTION_LOGIN_DENIED,
            success=False,
            error="account_disabled",
            actor_user_id=pre_row["id"],
            actor_email=normalized_email,
        )
        return _redirect_to_denied("account_disabled")

    user_row = _upsert_user(
        normalized_email=normalized_email,
        google_sub=google_sub,
        display_name=display_name,
        intended_role=access_entry["intended_role"],
    )
    # NOTE: the ON CONFLICT SET clause in _upsert_user does NOT include
    # account_status, so a row that was active pre-upsert is still active
    # post-upsert. If account_status is ever added to the SET clause, the
    # post-upsert denial check must be reinstated here.

    # Create the session row + cookie.
    from src.auth.sessions import create_session

    session_id = create_session(
        user_id=user_row["id"],
        user_agent=request.headers.get("User-Agent"),
        ip_first_seen=request.remote_addr,
    )

    response = redirect(next_target)
    set_session_cookie(response, session_id)

    _audit_login(
        action_type=_ACTION_LOGIN,
        success=True,
        error=None,
        actor_user_id=user_row["id"],
        actor_email=normalized_email,
        before_state=_user_snapshot(pre_row),
        after_state=_user_snapshot(user_row),
    )
    return response


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Revoke the current session and clear the cookie.

    POST-only so logout cannot be triggered cross-site via a ``<a>`` link
    or ``<img>`` tag.
    """
    from src.auth.cookies import get_session_id_from_request

    session_id = get_session_id_from_request(request)
    user = getattr(g, "user", None)

    if session_id:
        revoke_session(session_id)

    response = redirect("/")
    clear_session_cookie(response)

    _audit_login(
        action_type=_ACTION_LOGOUT,
        success=True,
        error=None,
        actor_user_id=user.id if user else None,
        actor_email=user.email if user else None,
    )
    return response


@auth_bp.route("/denied", methods=["GET"])
def denied():
    """Render the access-denied page.

    Wording for ``not_allowlisted`` and ``email_unverified`` is identical so
    the page does not leak which accounts are allowlisted. Other reasons
    (state mismatch, callback error, ID token invalid, account disabled)
    have more specific copy because they reveal nothing about allowlist
    membership.
    """
    reason = request.args.get("reason", "oauth_callback_error")
    return render_template("auth/denied.html", reason=reason), 403
