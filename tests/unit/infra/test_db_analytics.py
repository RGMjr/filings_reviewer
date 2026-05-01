"""Unit tests for the Phase-2 analytics helpers on DatabaseAdapter.

These helpers power the Metric Analytics Summary tab. We unit-test the SQL
shape (placeholder names, ORDER BY, LIMIT clamps) and the result-shape
transforms by mocking `DatabaseAdapter.query`. Integration tests against a
real Postgres live in tests/integration/.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.infra.db import DatabaseAdapter


@pytest.fixture
def db():
    """A DatabaseAdapter whose `query` is mocked. We never open a real connection."""
    adapter = DatabaseAdapter.__new__(DatabaseAdapter)  # bypass __init__
    adapter.query = MagicMock()  # type: ignore[method-assign]
    return adapter


class TestGetLastTrainingRun:
    def test_returns_dict_when_row_exists(self, db):
        ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
        db.query.return_value = [
            {
                "id": "uuid-1",
                "model_type": "image_relevance",
                "started_at": ts,
                "completed_at": ts,
                "status": "succeeded",
                "num_training_rows": 500,
                "num_positive_rows": 25,
                "model_path": "p",
                "report_path": None,
                "triggered_by": "RGM",
            }
        ]
        result = db.get_last_training_run("image_relevance")
        assert result is not None
        assert result["model_type"] == "image_relevance"
        assert result["completed_at"] == ts

    def test_returns_none_when_no_rows(self, db):
        db.query.return_value = []
        assert db.get_last_training_run("image_relevance") is None

    def test_filters_by_model_type_param(self, db):
        db.query.return_value = []
        db.get_last_training_run("some_other_model")
        sql, params = db.query.call_args[0]
        assert "model_type = %(model_type)s" in sql
        assert params == {"model_type": "some_other_model"}

    def test_only_returns_succeeded(self, db):
        db.query.return_value = []
        db.get_last_training_run("image_relevance")
        sql, _ = db.query.call_args[0]
        assert "status = 'succeeded'" in sql


class TestCountImageDecisionsSince:
    def test_splits_positive_and_negative(self, db):
        db.query.return_value = [{"total": 47, "positive": 6, "negative": 41}]
        result = db.count_image_decisions_since(datetime(2026, 5, 1, tzinfo=UTC))
        assert result == {"total": 47, "positive": 6, "negative": 41}

    def test_excludes_skip_from_total(self, db):
        db.query.return_value = []
        db.count_image_decisions_since(None)
        sql, _ = db.query.call_args[0]
        assert "FILTER (WHERE decision != 'skip')" in sql

    def test_positive_is_accept_correct_add(self, db):
        db.query.return_value = []
        db.count_image_decisions_since(None)
        sql, _ = db.query.call_args[0]
        assert "FILTER (WHERE decision IN ('accept', 'correct', 'add'))" in sql

    def test_handles_null_timestamp(self, db):
        db.query.return_value = []
        db.count_image_decisions_since(None)
        sql, params = db.query.call_args[0]
        # ::timestamptz cast is required so psycopg can infer the parameter
        # type when ts=None — without it, real Postgres raises
        # AmbiguousParameter (regression caught in prod 2026-05-01).
        assert "%(ts)s::timestamptz IS NULL" in sql
        assert params == {"ts": None}

    def test_zero_when_no_rows(self, db):
        db.query.return_value = []
        result = db.count_image_decisions_since(None)
        assert result == {"total": 0, "positive": 0, "negative": 0}


class TestCountTextDecisionsSince:
    def test_returns_count(self, db):
        db.query.return_value = [{"n": 12}]
        assert db.count_text_decisions_since(None) == 12

    def test_zero_when_no_rows(self, db):
        db.query.return_value = []
        assert db.count_text_decisions_since(None) == 0

    def test_passes_ts_param(self, db):
        db.query.return_value = []
        ts = datetime(2026, 5, 1, tzinfo=UTC)
        db.count_text_decisions_since(ts)
        _, params = db.query.call_args[0]
        assert params == {"ts": ts}


class TestRecentTextCorrections:
    def test_filters_to_correct(self, db):
        db.query.return_value = []
        db.get_recent_text_corrections(limit=5)
        sql, params = db.query.call_args[0]
        assert "rd.decision = 'correct'" in sql
        assert params == {"limit": 5}

    def test_orders_by_created_desc(self, db):
        db.query.return_value = []
        db.get_recent_text_corrections()
        sql, _ = db.query.call_args[0]
        assert "ORDER BY rd.created_at DESC" in sql

    def test_default_limit_is_10(self, db):
        db.query.return_value = []
        db.get_recent_text_corrections()
        _, params = db.query.call_args[0]
        assert params == {"limit": 10}

    def test_returns_dict_list(self, db):
        db.query.return_value = [
            {"fact_id": "f1", "original_metric_id": "cm_a", "corrected_metric_id": "cm_b"},
            {"fact_id": "f2", "original_metric_id": "cm_x", "corrected_metric_id": "cm_y"},
        ]
        result = db.get_recent_text_corrections()
        assert len(result) == 2
        assert all(isinstance(r, dict) for r in result)


class TestRecentTextAdditions:
    def test_filters_to_manual_extraction(self, db):
        db.query.return_value = []
        db.get_recent_text_additions()
        sql, _ = db.query.call_args[0]
        assert "mf.extraction_method = 'manual'" in sql

    def test_orders_by_created_desc(self, db):
        db.query.return_value = []
        db.get_recent_text_additions()
        sql, _ = db.query.call_args[0]
        assert "ORDER BY mf.created_at DESC" in sql


class TestRecentImageAdditions:
    def test_filters_to_add_decision(self, db):
        db.query.return_value = []
        db.get_recent_image_additions()
        sql, _ = db.query.call_args[0]
        assert "imc.decision = 'add'" in sql

    def test_orders_by_created_desc(self, db):
        db.query.return_value = []
        db.get_recent_image_additions()
        sql, _ = db.query.call_args[0]
        assert "ORDER BY imc.created_at DESC" in sql


class TestRecentImageCorrections:
    def test_filters_to_correct_decision(self, db):
        db.query.return_value = []
        db.get_recent_image_corrections()
        sql, _ = db.query.call_args[0]
        assert "imc.decision = 'correct'" in sql

    def test_includes_both_metric_ids(self, db):
        """A 'correct' has both detected and confirmed populated; surface both."""
        db.query.return_value = []
        db.get_recent_image_corrections()
        sql, _ = db.query.call_args[0]
        assert "imc.detected_metric_id" in sql
        assert "imc.confirmed_metric_id" in sql
