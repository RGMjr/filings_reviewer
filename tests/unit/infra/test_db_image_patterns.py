"""Unit tests for DatabaseAdapter.get_image_add_substrate.

SQL-shape tests only — verifies that the query filters decision='add',
joins v2_image_assets, and applies the nearby_text length floor. We mock
`DatabaseAdapter.query` and inspect the SQL string passed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.infra.db import DatabaseAdapter


def _make_db() -> DatabaseAdapter:
    adapter = DatabaseAdapter.__new__(DatabaseAdapter)
    adapter.query = MagicMock(return_value=[])  # type: ignore[method-assign]
    return adapter


class TestGetImageAddSubstrate:
    def test_filters_decision_add(self):
        db = _make_db()
        db.get_image_add_substrate()
        sql: str = db.query.call_args[0][0]
        assert "decision = 'add'" in sql

    def test_joins_v2_image_assets(self):
        db = _make_db()
        db.get_image_add_substrate()
        sql: str = db.query.call_args[0][0]
        assert "v2_image_assets" in sql

    def test_applies_nearby_text_length_floor(self):
        db = _make_db()
        db.get_image_add_substrate()
        sql: str = db.query.call_args[0][0]
        assert "nearby_text" in sql
        assert "length" in sql.lower()

    def test_selects_required_columns(self):
        db = _make_db()
        db.get_image_add_substrate()
        sql: str = db.query.call_args[0][0]
        assert "confirmed_metric_id" in sql
        assert "img_id" in sql
        assert "filing_id" in sql

    def test_returns_list_of_dicts(self):
        db = _make_db()
        db.query.return_value = [
            {
                "confirmed_metric_id": "cm_x",
                "img_id": "uuid-1",
                "filing_id": 42,
                "nearby_text": "purchase transactions volume",
            }
        ]
        result = db.get_image_add_substrate()
        assert isinstance(result, list)
        assert result[0]["confirmed_metric_id"] == "cm_x"
        assert result[0]["filing_id"] == 42

    def test_empty_rows_returns_empty_list(self):
        db = _make_db()
        db.query.return_value = []
        assert db.get_image_add_substrate() == []
