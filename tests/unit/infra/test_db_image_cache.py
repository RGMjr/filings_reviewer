"""
Unit tests for DatabaseAdapter image cache methods.
"""

from unittest.mock import MagicMock

import pytest

from src.infra.db import DatabaseAdapter


@pytest.fixture
def db():
    """DatabaseAdapter with mocked query method."""
    adapter = DatabaseAdapter.__new__(DatabaseAdapter)
    adapter.query = MagicMock()
    return adapter


class TestGetCachedImage:
    def test_returns_none_when_not_cached(self, db):
        db.query.return_value = []
        result = db.get_cached_image("1559720", "000119312520311265", "chart.jpg")
        assert result is None

    def test_returns_dict_on_hit(self, db):
        fake_bytes = b"\xff\xd8\xff"
        db.query.return_value = [
            {"image_data": fake_bytes, "content_type": "image/jpeg", "size_bytes": 3}
        ]
        result = db.get_cached_image("1559720", "000119312520311265", "chart.jpg")
        assert result is not None
        assert result["image_data"] == fake_bytes
        assert result["content_type"] == "image/jpeg"
        assert result["size_bytes"] == 3

    def test_query_uses_correct_params(self, db):
        db.query.return_value = []
        db.get_cached_image("1559720", "000119312520311265", "chart.jpg")
        call_kwargs = db.query.call_args
        params = call_kwargs[0][1]
        assert params["cik"] == "1559720"
        assert params["accession_no"] == "000119312520311265"
        assert params["filename"] == "chart.jpg"

    def test_image_data_coerced_to_bytes(self, db):
        # psycopg may return memoryview; ensure we return bytes
        db.query.return_value = [
            {"image_data": memoryview(b"\x89PNG"), "content_type": "image/png", "size_bytes": 4}
        ]
        result = db.get_cached_image("123", "000456", "img.png")
        assert isinstance(result["image_data"], bytes)


class TestStoreCachedImage:
    def test_returns_true_when_inserted(self, db):
        db.query.return_value = [{"cik": "1559720"}]
        result = db.store_cached_image("1559720", "000119312520311265", "chart.jpg", b"data", "image/jpeg")
        assert result is True

    def test_returns_false_on_conflict(self, db):
        db.query.return_value = []  # ON CONFLICT DO NOTHING returns nothing
        result = db.store_cached_image("1559720", "000119312520311265", "chart.jpg", b"data", "image/jpeg")
        assert result is False

    def test_size_bytes_computed_from_data(self, db):
        db.query.return_value = [{"cik": "123"}]
        image_data = b"x" * 500
        db.store_cached_image("123", "000456", "img.jpg", image_data, "image/jpeg")
        params = db.query.call_args[0][1]
        assert params["size_bytes"] == 500

    def test_query_uses_correct_params(self, db):
        db.query.return_value = []
        db.store_cached_image("123", "000456", "img.png", b"\x89PNG", "image/png")
        params = db.query.call_args[0][1]
        assert params["cik"] == "123"
        assert params["accession_no"] == "000456"
        assert params["filename"] == "img.png"
        assert params["content_type"] == "image/png"


class TestGetImageCacheStats:
    def test_returns_count_and_total_bytes(self, db):
        db.query.return_value = [{"count": 42, "total_bytes": 1024000}]
        stats = db.get_image_cache_stats()
        assert stats == {"count": 42, "total_bytes": 1024000}

    def test_empty_table(self, db):
        db.query.return_value = [{"count": 0, "total_bytes": 0}]
        stats = db.get_image_cache_stats()
        assert stats["count"] == 0
        assert stats["total_bytes"] == 0
