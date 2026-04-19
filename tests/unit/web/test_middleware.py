"""
Unit tests for src/web/middleware.py.

Currently exercises the audit-log failure-logging branch: ERROR in production,
DEBUG under `TESTING=True` (so pytest output stays clean when `DATABASE_URL`
is a test sentinel). See KNOWN_ISSUES.md #31.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

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

        messages = [(r.levelno, r.getMessage()) for r in caplog.records
                    if r.name == "src.web.middleware"]
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

        messages = [(r.levelno, r.getMessage()) for r in caplog.records
                    if r.name == "src.web.middleware"]
        assert any(lvl == logging.ERROR and "boom" in msg for lvl, msg in messages)
