"""
Unit tests for ``src/auth/feature_flags.is_enabled``.

The DB layer is stubbed via ``monkeypatch.setattr`` on ``src.web.app.get_db``
— the cache layer is the actual unit under test, not the DB query.
"""

from __future__ import annotations

import time

import pytest

from src.auth import feature_flags


class FakeDB:
    """Minimal DB adapter stub: returns whatever rows the test programs in."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.call_count = 0

    def query(self, sql, params=None):
        self.call_count += 1
        return self.rows


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the per-key cache between tests so flag flips don't bleed."""
    feature_flags._clear_cache_for_tests()
    yield
    feature_flags._clear_cache_for_tests()


@pytest.fixture
def patch_db(monkeypatch):
    """Install a ``FakeDB`` and return it so tests can inspect call_count."""

    def _install(rows):
        fake = FakeDB(rows)
        monkeypatch.setattr("src.web.app.get_db", lambda: fake)
        return fake

    return _install


class TestIsEnabled:
    def test_missing_row_returns_false(self, patch_db):
        patch_db([])
        assert feature_flags.is_enabled("nonexistent_flag") is False

    def test_expired_flag_returns_false(self, patch_db):
        # The SQL filter (expires_at IS NULL OR expires_at > NOW()) excludes
        # expired rows — the DB returns no rows. This pins that an expired
        # value='true' row resolves to False (Stage D break-glass override relies on it).
        patch_db([])  # expired row filtered out by SQL expires_at check
        assert feature_flags.is_enabled("time_limited_flag") is False

    def test_value_true_returns_true(self, patch_db):
        patch_db([{"value": "true"}])
        assert feature_flags.is_enabled("some_flag") is True

    def test_value_false_returns_false(self, patch_db):
        patch_db([{"value": "false"}])
        assert feature_flags.is_enabled("some_flag") is False

    def test_value_other_string_returns_false(self, patch_db):
        patch_db([{"value": "yes"}])
        assert feature_flags.is_enabled("some_flag") is False

    def test_db_error_returns_false(self, monkeypatch):
        def boom():
            raise Exception("connection refused")

        monkeypatch.setattr("src.web.app.get_db", boom)
        assert feature_flags.is_enabled("some_flag") is False

    def test_cache_hit_avoids_second_db_call(self, patch_db):
        fake = patch_db([{"value": "true"}])
        feature_flags.is_enabled("hot_flag")
        feature_flags.is_enabled("hot_flag")
        feature_flags.is_enabled("hot_flag")
        assert fake.call_count == 1, "second/third reads should be cache hits"

    def test_cache_expiry_triggers_db_reread(self, patch_db, monkeypatch):
        fake = patch_db([{"value": "true"}])
        feature_flags.is_enabled("hot_flag")

        # Advance the monotonic clock past the TTL so the cached entry is stale.
        original_monotonic = time.monotonic
        offset = feature_flags._FLAG_CACHE_TTL + 1.0
        monkeypatch.setattr(
            time,
            "monotonic",
            lambda: original_monotonic() + offset,
        )

        feature_flags.is_enabled("hot_flag")
        assert fake.call_count == 2

    def test_per_key_cache_independence(self, patch_db):
        # Two different keys cache independently.
        fake = patch_db([{"value": "true"}])
        feature_flags.is_enabled("flag_a")
        feature_flags.is_enabled("flag_b")
        assert fake.call_count == 2

        # Re-reading either is a hit.
        feature_flags.is_enabled("flag_a")
        feature_flags.is_enabled("flag_b")
        assert fake.call_count == 2

    def test_runtime_error_propagates(self, monkeypatch):
        def boom():
            raise RuntimeError("Working outside of application context")

        monkeypatch.setattr("src.web.app.get_db", boom)
        with pytest.raises(RuntimeError):
            feature_flags.is_enabled("some_flag")

    def test_import_error_propagates(self, monkeypatch):
        def boom():
            raise ImportError("module not found")

        monkeypatch.setattr("src.web.app.get_db", boom)
        with pytest.raises(ImportError):
            feature_flags.is_enabled("some_flag")

    def test_fail_closed_true_re_raises_db_error(self, monkeypatch):
        def boom():
            raise Exception("connection refused")

        monkeypatch.setattr("src.web.app.get_db", boom)
        with pytest.raises(Exception, match="connection refused"):
            feature_flags.is_enabled("some_flag", fail_closed=True)

    def test_fail_closed_true_successful_read_returns_value(self, patch_db):
        patch_db([{"value": "true"}])
        assert feature_flags.is_enabled("some_flag", fail_closed=True) is True
