"""Tests for the centralized Sentry init (src/infra/sentry.py).

These exercise init_sentry() against a fake but well-formed DSN. The autouse
fixture resets the global Sentry client to a NonRecordingClient before and
after each test so an activated client never leaks across tests.
"""

import sentry_sdk
from sentry_sdk.client import NonRecordingClient

from src.infra.sentry import _EXTRA_DENYLIST, init_sentry

# Well-formed but fake DSN — never sends because the test transport is never
# flushed and the project key/host are not real.
_FAKE_DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"


def _reset_client() -> None:
    sentry_sdk.get_global_scope().set_client(NonRecordingClient())


def setup_function() -> None:
    _reset_client()


def teardown_function() -> None:
    _reset_client()


def test_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry("development") is False
    assert sentry_sdk.get_client().is_active() is False


def test_skips_under_testing_config(monkeypatch):
    # Even with a DSN present, the testing config must not activate Sentry —
    # this is the guard that keeps the test suite from emitting events.
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    assert init_sentry("testing") is False
    assert sentry_sdk.get_client().is_active() is False


def test_app_env_falls_back_to_environ(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    monkeypatch.setenv("APP_ENV", "testing")
    # No explicit app_env -> reads APP_ENV -> "testing" -> skip.
    assert init_sentry() is False
    assert sentry_sdk.get_client().is_active() is False


def test_active_path_sets_hardened_options(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert init_sentry("development") is True

    client = sentry_sdk.get_client()
    assert client.is_active() is True
    opts = client.options
    # Errors only — protects the free-tier shared quota.
    assert opts["traces_sample_rate"] == 0.0
    assert opts["profiles_sample_rate"] == 0.0
    # PII never sent.
    assert opts["send_default_pii"] is False
    assert opts["environment"] == "development"


def test_release_tagged_from_render_git_commit(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234")
    assert init_sentry("production") is True
    assert sentry_sdk.get_client().options["release"] == "abc1234"


def test_scrubber_includes_project_keys(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    init_sentry("development")
    scrubber = sentry_sdk.get_client().options["event_scrubber"]
    # A representative reviewer-PII key and a secret key are both on the denylist.
    assert "reviewer_id" in scrubber.denylist
    assert "database_url" in scrubber.denylist
    # Every project-specific key we declared made it in.
    for key in _EXTRA_DENYLIST:
        assert key in scrubber.denylist


def test_scrubber_filters_sensitive_extra(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    init_sentry("development")
    scrubber = sentry_sdk.get_client().options["event_scrubber"]

    event = {"extra": {"reviewer_id": "RGM", "database_url": "postgresql://u:p@h/db", "safe": "ok"}}
    scrubber.scrub_event(event)

    # Denylisted values are replaced (with an AnnotatedValue); safe values stay.
    assert event["extra"]["reviewer_id"] != "RGM"
    assert event["extra"]["database_url"] != "postgresql://u:p@h/db"
    assert event["extra"]["safe"] == "ok"


def test_idempotent(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    assert init_sentry("development") is True
    first_client = sentry_sdk.get_client()
    # Second call is a no-op that returns True without re-initializing.
    assert init_sentry("development") is True
    assert sentry_sdk.get_client() is first_client
