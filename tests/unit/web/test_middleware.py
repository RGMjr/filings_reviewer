"""
Unit tests for src/web/middleware.py.

Currently exercises the audit-log failure-logging branch: ERROR in production,
DEBUG under `TESTING=True` (so pytest output stays clean when `DATABASE_URL`
is a test sentinel). See KNOWN_ISSUES.md #31.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

from src.auth.service_account import _SERVICE_ACCOUNT, SERVICE_ACCOUNT_ID
from src.web.middleware import insert_audit_log_entry


@pytest.fixture
def app():
    flask_app = Flask(__name__)
    flask_app.config["DATABASE_URL"] = "postgresql://test"
    flask_app.secret_key = "test-secret"
    return flask_app


def _make_response():
    resp = MagicMock()
    resp.status_code = 200
    return resp


class TestAuditLogFailureLogging:
    def test_failure_logs_debug_under_testing(self, app, caplog):
        app.config["TESTING"] = True
        failing_db = MagicMock()
        failing_db.insert_audit_log.side_effect = RuntimeError("boom")

        with patch("src.web.app.get_db", return_value=failing_db):
            with app.test_request_context("/some/path"):
                with caplog.at_level(logging.DEBUG, logger="src.web.middleware"):
                    insert_audit_log_entry(_make_response(), filing_id=42)

        messages = [
            (r.levelno, r.getMessage()) for r in caplog.records if r.name == "src.web.middleware"
        ]
        assert any(lvl == logging.DEBUG and "boom" in msg for lvl, msg in messages)
        assert not any(lvl == logging.ERROR for lvl, _ in messages)

    def test_failure_logs_error_outside_testing(self, app, caplog):
        app.config["TESTING"] = False
        failing_db = MagicMock()
        failing_db.insert_audit_log.side_effect = RuntimeError("boom")

        with patch("src.web.app.get_db", return_value=failing_db):
            with app.test_request_context("/some/path"):
                with caplog.at_level(logging.DEBUG, logger="src.web.middleware"):
                    insert_audit_log_entry(_make_response(), filing_id=42)

        messages = [
            (r.levelno, r.getMessage()) for r in caplog.records if r.name == "src.web.middleware"
        ]
        assert any(lvl == logging.ERROR and "boom" in msg for lvl, msg in messages)


class TestAuditLogUserId:
    """gh-520: insert_audit_log_entry must forward `flask.g.user.id` to the DB write."""

    def test_user_id_from_g_is_forwarded(self, app):
        db = MagicMock()
        db.insert_audit_log.return_value = 1

        fake_user = MagicMock()
        fake_user.id = "11111111-2222-3333-4444-555555555555"

        with patch("src.web.app.get_db", return_value=db):
            with app.test_request_context("/some/path"):
                g.user = fake_user
                insert_audit_log_entry(_make_response(), filing_id=42)

        assert db.insert_audit_log.call_args.kwargs["user_id"] == fake_user.id

    def test_user_id_is_sentinel_for_service_account(self, app):
        db = MagicMock()
        db.insert_audit_log.return_value = 1

        with patch("src.web.app.get_db", return_value=db):
            with app.test_request_context("/some/path"):
                g.user = _SERVICE_ACCOUNT
                insert_audit_log_entry(_make_response(), filing_id=42)

        assert db.insert_audit_log.call_args.kwargs["user_id"] == SERVICE_ACCOUNT_ID

    def test_user_id_is_none_when_g_user_unset(self, app):
        db = MagicMock()
        db.insert_audit_log.return_value = 1

        with patch("src.web.app.get_db", return_value=db):
            with app.test_request_context("/some/path"):
                # g.user deliberately unset (e.g., audit hook fires before auth load)
                insert_audit_log_entry(_make_response(), filing_id=42)

        assert db.insert_audit_log.call_args.kwargs["user_id"] is None
