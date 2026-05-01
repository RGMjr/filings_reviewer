"""Unit tests for src/auth/dev_bypass.py."""

import pytest

from src.auth.dev_bypass import dev_bypass_user, is_dev_bypass_enabled, verify_dev_bypass_safe

# ---------------------------------------------------------------------------
# is_dev_bypass_enabled
# ---------------------------------------------------------------------------


def test_bypass_enabled_when_set_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_DEV_BYPASS", "1")
    assert is_dev_bypass_enabled() is True


def test_bypass_disabled_when_set_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_DEV_BYPASS", "0")
    assert is_dev_bypass_enabled() is False


def test_bypass_disabled_when_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_DEV_BYPASS", "")
    assert is_dev_bypass_enabled() is False


def test_bypass_disabled_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_DEV_BYPASS", raising=False)
    assert is_dev_bypass_enabled() is False


def test_bypass_disabled_when_set_to_true_string(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the exact string "1" enables bypass.
    monkeypatch.setenv("AUTH_DEV_BYPASS", "true")
    assert is_dev_bypass_enabled() is False


# ---------------------------------------------------------------------------
# verify_dev_bypass_safe
# ---------------------------------------------------------------------------


def test_raises_in_production_with_bypass_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production + bypass set => RuntimeError (security misconfiguration)."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_BYPASS", "1")
    with pytest.raises(RuntimeError, match="AUTH_DEV_BYPASS=1"):
        verify_dev_bypass_safe()


def test_no_raise_in_production_without_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production + bypass unset => safe, returns None."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AUTH_DEV_BYPASS", raising=False)
    result = verify_dev_bypass_safe()
    assert result is None


def test_no_raise_in_development_with_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev + bypass set => allowed (local development use case)."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_BYPASS", "1")
    result = verify_dev_bypass_safe()
    assert result is None


def test_no_raise_when_app_env_unset_with_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV unset defaults to development => bypass is safe."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("AUTH_DEV_BYPASS", "1")
    result = verify_dev_bypass_safe()
    assert result is None


def test_no_raise_in_testing_with_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Testing env + bypass => allowed (CI / test suite use case)."""
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("AUTH_DEV_BYPASS", "1")
    result = verify_dev_bypass_safe()
    assert result is None


def test_error_message_mentions_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """RuntimeError message should mention APP_ENV so operators know what to fix."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_BYPASS", "1")
    with pytest.raises(RuntimeError, match="APP_ENV=production"):
        verify_dev_bypass_safe()


# ---------------------------------------------------------------------------
# dev_bypass_user
# ---------------------------------------------------------------------------


def test_dev_bypass_user_has_admin_role() -> None:
    user = dev_bypass_user()
    assert "admin" in user.roles


def test_dev_bypass_user_is_authenticated() -> None:
    user = dev_bypass_user()
    assert user.is_authenticated is True


def test_dev_bypass_user_has_expected_attrs() -> None:
    user = dev_bypass_user()
    assert hasattr(user, "user_id")
    assert hasattr(user, "email")
    assert hasattr(user, "name")
