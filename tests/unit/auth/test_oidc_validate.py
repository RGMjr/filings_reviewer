"""
Unit tests for ``src/auth/oidc_validate.validate_id_token``.

The Google library's signature/aud/exp checks are stubbed via monkeypatching
``google.oauth2.id_token.verify_oauth2_token``. The application-level checks
(iss / nonce / email_verified) are exercised against the returned claims dict.
"""

from __future__ import annotations

import pytest

from src.auth.oidc_validate import OidcValidationError, validate_id_token

CLIENT_ID = "test-client-id"
EXPECTED_NONCE = "expected-nonce-value"


def _good_claims(**overrides):
    """Return a minimal valid claims dict for happy-path tests."""
    base = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-sub-123",
        "email": "user@example.com",
        "email_verified": True,
        "nonce": EXPECTED_NONCE,
        "name": "Test User",
    }
    base.update(overrides)
    return base


@pytest.fixture
def stub_verify(monkeypatch):
    """Stub ``google.oauth2.id_token.verify_oauth2_token`` to return controlled claims."""

    def _factory(claims_or_exc):
        def fake_verify(id_token, transport, audience):
            if isinstance(claims_or_exc, Exception):
                raise claims_or_exc
            return claims_or_exc

        monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", fake_verify)

    return _factory


class TestValidateIdToken:
    def test_happy_path_returns_claims(self, stub_verify):
        claims = _good_claims()
        stub_verify(claims)

        result = validate_id_token(
            "fake-token",
            client_id=CLIENT_ID,
            expected_nonce=EXPECTED_NONCE,
        )

        assert result["sub"] == "google-sub-123"
        assert result["email"] == "user@example.com"

    def test_signature_failure_raises_invalid(self, stub_verify):
        stub_verify(ValueError("bad signature"))

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "oauth_id_token_invalid"

    def test_wrong_aud_raises_invalid(self, stub_verify):
        # google-auth raises ValueError("Could not verify token signature")
        # on aud mismatch — pins behavior against silent library regressions.
        stub_verify(ValueError("Could not verify token signature"))

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "oauth_id_token_invalid"

    def test_unknown_issuer_raises_invalid(self, stub_verify):
        stub_verify(_good_claims(iss="https://evil.com"))

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "oauth_id_token_invalid"

    def test_alternate_issuer_format_passes(self, stub_verify):
        # Google accepts both forms — accounts.google.com without scheme.
        stub_verify(_good_claims(iss="accounts.google.com"))

        result = validate_id_token(
            "fake-token",
            client_id=CLIENT_ID,
            expected_nonce=EXPECTED_NONCE,
        )
        assert result["iss"] == "accounts.google.com"

    def test_nonce_mismatch_raises_invalid(self, stub_verify):
        stub_verify(_good_claims(nonce="wrong-nonce"))

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "oauth_id_token_invalid"

    def test_missing_nonce_raises_invalid(self, stub_verify):
        claims = _good_claims()
        del claims["nonce"]
        stub_verify(claims)

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "oauth_id_token_invalid"

    def test_email_unverified_raises_unverified(self, stub_verify):
        stub_verify(_good_claims(email_verified=False))

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "email_unverified"

    def test_email_verified_missing_raises_unverified(self, stub_verify):
        claims = _good_claims()
        del claims["email_verified"]
        stub_verify(claims)

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "email_unverified"

    def test_email_verified_truthy_string_rejected(self, stub_verify):
        # Strict ``is True`` — only a Python bool True passes.
        stub_verify(_good_claims(email_verified="true"))

        with pytest.raises(OidcValidationError) as excinfo:
            validate_id_token(
                "fake-token",
                client_id=CLIENT_ID,
                expected_nonce=EXPECTED_NONCE,
            )
        assert excinfo.value.reason == "email_unverified"
