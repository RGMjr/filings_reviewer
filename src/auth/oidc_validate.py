"""
ID token validation for the Google OAuth login flow.

Wraps ``google.oauth2.id_token.verify_oauth2_token`` (signature, ``aud``,
``exp``) and adds the spec-required application-level checks (``iss``,
``nonce``, ``email_verified``).

Library choice: ``google-auth`` is the maintained Google library for Google
ID tokens. Rolling JWT validation by hand is explicitly out of scope per
spec §OAuth/OIDC Implementation Requirements.

The transport (a ``google.auth.transport.requests.Request`` wrapping a
``requests.Session``) is created once and reused across calls — the Google
library uses it to fetch and cache the JWKS, so reusing it avoids a JWKS
round-trip per login.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Google's two acceptable ``iss`` values (per the OpenID Connect Discovery
# document at https://accounts.google.com/.well-known/openid-configuration).
_VALID_ISSUERS: frozenset[str] = frozenset({"https://accounts.google.com", "accounts.google.com"})


# Module-level transport instance so JWKS fetches are cached across calls.
# Lazily initialised so importing this module does not require google-auth.
_TRANSPORT: Any | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OidcValidationError(Exception):
    """Raised when an ID token fails validation.

    ``reason`` is a short stable identifier suitable for audit logs and the
    ``/auth/denied?reason=`` query parameter. Only two values surface to the
    user-facing audit trail today:

      - ``"oauth_id_token_invalid"`` — signature, ``aud``, ``iss``, ``exp``,
        or ``nonce`` failure (everything except the email check).
      - ``"email_unverified"`` — ID token is otherwise valid but
        ``email_verified`` is false (or missing).
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


# ---------------------------------------------------------------------------
# Transport (JWKS fetcher)
# ---------------------------------------------------------------------------


def _get_transport() -> Any:
    """Return a cached ``google.auth.transport.requests.Request`` instance."""
    global _TRANSPORT
    if _TRANSPORT is None:
        from google.auth.transport import requests as google_requests

        _TRANSPORT = google_requests.Request()
    return _TRANSPORT


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_id_token(
    id_token_str: str,
    *,
    client_id: str,
    expected_nonce: str,
) -> dict:
    """Validate a Google ID token and return its decoded claims.

    Validation order (each step raises ``OidcValidationError`` on failure):

    1. Signature, ``aud == client_id``, and ``exp`` in the future
       (``google.oauth2.id_token.verify_oauth2_token``).
    2. ``iss`` is a known Google issuer.
    3. ``nonce`` matches *expected_nonce*.
    4. ``email_verified`` is exactly the boolean ``True``.

    The first failure short-circuits — we never check ``email_verified`` on
    a token whose signature didn't validate.

    Args:
        id_token_str: The raw ID token string from the token-exchange response.
        client_id: The Google OAuth client id (the ``aud`` value).
        expected_nonce: The nonce value the app generated at login start.

    Returns:
        The decoded claims dict (``sub``, ``email``, ``email_verified``,
        ``name``, etc.).

    Raises:
        OidcValidationError: with ``reason='oauth_id_token_invalid'`` for
            signature/aud/iss/exp/nonce failures, or
            ``reason='email_unverified'`` when the email isn't verified.
    """
    from google.auth.exceptions import GoogleAuthError
    from google.oauth2 import id_token as google_id_token

    transport = _get_transport()

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str,
            transport,
            audience=client_id,
        )
    except (GoogleAuthError, ValueError) as exc:
        # google-auth raises ValueError on shape problems and GoogleAuthError
        # on signature/expiry/aud failures. Treat both as the same reason —
        # the user-visible page should not differentiate.
        logger.info("ID token signature/aud/exp validation failed: %s", exc)
        raise OidcValidationError(
            "oauth_id_token_invalid",
            f"signature/aud/exp validation failed: {exc}",
        ) from exc

    # Issuer check — verify_oauth2_token does this internally for the two
    # accepted issuers, but be defensive against future library changes.
    iss = claims.get("iss")
    if iss not in _VALID_ISSUERS:
        raise OidcValidationError(
            "oauth_id_token_invalid",
            f"unexpected iss claim: {iss!r}",
        )

    # Nonce check — must match exactly the value the app generated at login
    # start. Replayed callbacks (or callbacks where the nonce was tampered
    # with) fail here.
    if claims.get("nonce") != expected_nonce:
        raise OidcValidationError(
            "oauth_id_token_invalid",
            "nonce mismatch (replayed or tampered callback)",
        )

    # Email-verified check. Note: Google sends this as a JSON boolean, which
    # google-auth surfaces as a Python bool. Be strict — accept only True.
    if claims.get("email_verified") is not True:
        raise OidcValidationError(
            "email_unverified",
            "Google reports email_verified=false",
        )

    return claims
