"""
OAuth 2.0 Authorization Code with PKCE — Google login flow.

Pure-Python helpers for the Google OAuth flow used by ``src/web/routes/auth.py``.
No Flask coupling here — every function takes its inputs as plain arguments
and returns plain data. This keeps the flow testable without a request context.

Flow:
  1. ``GET /auth/login`` calls ``generate_state``, ``generate_nonce``, and
     ``generate_pkce_pair``; stashes them in the Flask framework session;
     redirects the browser to ``build_authorization_url(...)``.
  2. Google redirects back to ``GET /auth/callback?code=...&state=...``.
     The route handler verifies ``state``, then calls
     ``exchange_code_for_tokens(code, code_verifier, ...)``.
  3. The handler then validates the returned ``id_token`` via
     ``src.auth.oidc_validate.validate_id_token``.

The exchange uses the existing project ``requests`` dependency. Errors raise
``OAuthExchangeError`` with a short reason string the caller can include in
audit logs.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import urllib.parse

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints (Google OAuth 2.0)
# ---------------------------------------------------------------------------

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Network timeout for the token exchange. Keep tight — the user is waiting
# on the redirect to complete and a slow exchange should fail fast rather
# than hold the request open.
TOKEN_EXCHANGE_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OAuthExchangeError(Exception):
    """Raised when the Google token exchange fails.

    ``reason`` is a short stable identifier suitable for audit logs and the
    ``/auth/denied?reason=`` query parameter (e.g. ``"oauth_callback_error"``).
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


# ---------------------------------------------------------------------------
# State / nonce / PKCE generation
# ---------------------------------------------------------------------------


def generate_state() -> str:
    """Return a fresh ``state`` parameter (URL-safe random)."""
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    """Return a fresh ``nonce`` parameter (URL-safe random)."""
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE ``(code_verifier, code_challenge)`` pair.

    The verifier is a cryptographically random URL-safe string. The challenge
    is the base64url-encoded SHA-256 of the verifier with padding stripped,
    per RFC 7636 §4.2.

    Returns:
        ``(code_verifier, code_challenge)`` — both URL-safe ASCII strings.
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# ---------------------------------------------------------------------------
# Authorization URL
# ---------------------------------------------------------------------------


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    """Return the Google authorization URL for the start of the flow.

    Scopes are ``openid email profile`` (per spec §OAuth Implementation
    Requirements — only what's needed to identify the user). ``prompt=
    select_account`` so users with multiple Google accounts get to pick.

    Args:
        client_id: Google OAuth 2.0 client id.
        redirect_uri: Callback URI registered in Google Cloud Console.
        state: Random state parameter (also stored server-side for callback verification).
        nonce: Random nonce parameter (verified inside the ID token).
        code_challenge: PKCE challenge derived from the verifier.

    Returns:
        The fully-formed authorization URL the browser should be redirected to.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def exchange_code_for_tokens(
    *,
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    """Exchange the authorization ``code`` for tokens via Google's token endpoint.

    Args:
        code: The authorization code returned in the callback query string.
        code_verifier: The PKCE verifier saved at login start.
        client_id: Google OAuth client id.
        client_secret: Google OAuth client secret.
        redirect_uri: The same redirect URI used in the auth URL.

    Returns:
        The JSON response dict — must contain at minimum ``id_token``.

    Raises:
        OAuthExchangeError: with ``reason='oauth_callback_error'`` on any
            non-200 response, network error, or missing ``id_token`` field.
    """
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    try:
        response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data=payload,
            timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("OAuth token exchange network error: %s", exc)
        raise OAuthExchangeError(
            "oauth_callback_error",
            f"network error talking to Google token endpoint: {exc}",
        ) from exc

    if response.status_code != 200:
        # Don't log the response body unconditionally — Google echoes the
        # client secret in some error paths. Log only the status and a short tag.
        logger.warning("OAuth token exchange returned HTTP %s", response.status_code)
        raise OAuthExchangeError(
            "oauth_callback_error",
            f"token endpoint returned HTTP {response.status_code}",
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise OAuthExchangeError(
            "oauth_callback_error",
            "token endpoint returned non-JSON body",
        ) from exc

    if not isinstance(body, dict) or "id_token" not in body:
        raise OAuthExchangeError(
            "oauth_callback_error",
            "token endpoint response missing id_token field",
        )

    return body
