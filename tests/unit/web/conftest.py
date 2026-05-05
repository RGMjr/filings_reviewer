"""
Unit-test conftest for tests/unit/web/.

Stubs ``is_enabled`` so that ``create_app()`` calls inside unit tests never
attempt a live DB round-trip to read the ``google_login_enabled`` flag.

Background: ``create_app()`` calls ``is_enabled("google_login_enabled",
fail_closed=True)`` at boot time.  With ``fail_closed=True``, any exception
(including DB-unreachable errors in a test environment that lacks a real
database) propagates instead of silently defaulting to False.  Unit tests don't
run against a live database, so we stub the flag reader to return False for all
keys, which preserves the pre-existing test contract (auth blueprint not
registered during unit tests) without triggering a DB connection.

Tests that need specific flag values can override via ``monkeypatch.setattr``
in their own fixtures — a local patch always wins.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stub_is_enabled_for_create_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent boot-time DB flag reads in create_app() for all web unit tests."""
    monkeypatch.setattr(
        "src.auth.feature_flags.is_enabled",
        lambda *args, **kwargs: False,
    )
