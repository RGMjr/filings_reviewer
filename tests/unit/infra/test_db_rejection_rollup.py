"""Unit tests for db.get_rejection_reason_rollup (Phase 4c).

The helper aggregates rejected decisions by category for the "Why Reviewers
Reject" panel on the Metric Analytics Summary tab. We unit-test the SQL
shape (correct table per side, correct decision filter, NULL exclusion)
and the side-validation guard. Result-shape transforms are deferred to
the integration test in gh-389.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.infra.db import DatabaseAdapter


@pytest.fixture
def db():
    adapter = DatabaseAdapter.__new__(DatabaseAdapter)
    adapter.query = MagicMock()  # type: ignore[method-assign]
    return adapter


class TestRejectionRollup:
    def test_invalid_side_raises(self, db):
        with pytest.raises(ValueError, match="Unknown side"):
            db.get_rejection_reason_rollup("audio")

    def test_text_side_reads_v2_review_decisions(self, db):
        db.query.return_value = []
        db.get_rejection_reason_rollup("text")
        sql, params = db.query.call_args[0]
        assert "v2_review_decisions" in sql
        assert "rejection_category" in sql
        assert "v2_image_metric_confirmations" not in sql

    def test_image_side_reads_v2_image_metric_confirmations(self, db):
        db.query.return_value = []
        db.get_rejection_reason_rollup("image")
        sql, _ = db.query.call_args[0]
        assert "v2_image_metric_confirmations" in sql
        assert "rejection_reason" in sql
        assert "v2_review_decisions" not in sql

    def test_filters_to_reject_decisions_only(self, db):
        db.query.return_value = []
        db.get_rejection_reason_rollup("text")
        sql, _ = db.query.call_args[0]
        assert "decision = 'reject'" in sql

    def test_excludes_null_reasons(self, db):
        # NULL rejection_category / rejection_reason rows would skew the rollup
        # — confirm they're filtered out.
        db.query.return_value = []
        db.get_rejection_reason_rollup("text")
        sql, _ = db.query.call_args[0]
        assert "IS NOT NULL" in sql

    def test_since_filter_uses_named_param(self, db):
        ts = datetime(2026, 5, 1, tzinfo=UTC)
        db.query.return_value = []
        db.get_rejection_reason_rollup("text", since=ts)
        sql, params = db.query.call_args[0]
        assert "%(since)s" in sql
        assert params == {"since": ts}

    def test_since_none_returns_lifetime_totals(self, db):
        db.query.return_value = []
        db.get_rejection_reason_rollup("image", since=None)
        sql, params = db.query.call_args[0]
        # ::timestamptz cast is required so psycopg can infer the parameter
        # type when since=None — without it, real Postgres raises
        # AmbiguousParameter (regression caught in prod 2026-05-01).
        assert "%(since)s::timestamptz IS NULL" in sql
        assert params == {"since": None}

    def test_orders_by_count_desc(self, db):
        db.query.return_value = []
        db.get_rejection_reason_rollup("image")
        sql, _ = db.query.call_args[0]
        assert "ORDER BY count DESC" in sql

    def test_returns_dict_list(self, db):
        db.query.return_value = [
            {"reason": "wrong_metric", "count": 5, "percent": 50.0},
            {"reason": "duplicate", "count": 3, "percent": 30.0},
        ]
        result = db.get_rejection_reason_rollup("text")
        assert len(result) == 2
        assert all(isinstance(r, dict) for r in result)
        assert result[0]["reason"] == "wrong_metric"
