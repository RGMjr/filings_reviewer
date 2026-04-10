"""
Unit tests for SECClient DB-backed image cache (db_adapter parameter).
"""

from unittest.mock import MagicMock

import pytest

from src.infra.http_client import HTTPResponse
from src.infra.sec_client import SECClient
from tests.unit.infra.mock_http_client import MockHTTPClient

IMAGE_URL = "https://www.sec.gov/Archives/edgar/data/1559720/000119312520311265/chart.jpg"
FAKE_IMAGE = b"\xff\xd8\xff\xe0"  # minimal JPEG header


def _make_image_response(content=FAKE_IMAGE, content_type="image/jpeg"):
    return HTTPResponse(
        status_code=200,
        content=content,
        headers={"Content-Type": content_type},
        url=IMAGE_URL,
        elapsed_seconds=0.05,
    )


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_cached_image.return_value = None  # cache miss by default
    db.store_cached_image.return_value = True
    return db


@pytest.fixture
def mock_http():
    client = MockHTTPClient()
    client.responses[IMAGE_URL] = _make_image_response()
    return client


class TestFetchImageDbCacheHit:
    def test_returns_cached_bytes_without_http(self, mock_db, mock_http):
        cached_bytes = b"cached image data"
        mock_db.get_cached_image.return_value = {
            "image_data": cached_bytes,
            "content_type": "image/jpeg",
            "size_bytes": len(cached_bytes),
        }
        sec = SECClient(http_client=mock_http, db_adapter=mock_db)
        result = sec.fetch_image("1559720", "0001193125-20-311265", "chart.jpg")
        assert result == cached_bytes
        assert mock_http.get_request_count() == 0  # no HTTP call made

    def test_db_cache_hit_uses_stripped_cik(self, mock_db, mock_http):
        mock_db.get_cached_image.return_value = {
            "image_data": b"data",
            "content_type": "image/jpeg",
            "size_bytes": 4,
        }
        sec = SECClient(http_client=mock_http, db_adapter=mock_db)
        sec.fetch_image("01559720", "0001193125-20-311265", "chart.jpg")  # padded CIK
        call_args = mock_db.get_cached_image.call_args[0]
        assert call_args[0] == "1559720"  # leading zero stripped

    def test_db_cache_hit_uses_no_dashes_accession(self, mock_db, mock_http):
        mock_db.get_cached_image.return_value = {
            "image_data": b"data",
            "content_type": "image/jpeg",
            "size_bytes": 4,
        }
        sec = SECClient(http_client=mock_http, db_adapter=mock_db)
        sec.fetch_image("1559720", "0001193125-20-311265", "chart.jpg")
        call_args = mock_db.get_cached_image.call_args[0]
        assert call_args[1] == "000119312520311265"  # dashes removed


class TestFetchImageDbCacheMiss:
    def test_fetches_from_sec_on_miss(self, mock_db, mock_http):
        sec = SECClient(http_client=mock_http, db_adapter=mock_db)
        result = sec.fetch_image("1559720", "0001193125-20-311265", "chart.jpg")
        assert result == FAKE_IMAGE
        assert mock_http.get_request_count() == 1

    def test_stores_in_db_after_fetch(self, mock_db, mock_http):
        sec = SECClient(http_client=mock_http, db_adapter=mock_db)
        sec.fetch_image("1559720", "0001193125-20-311265", "chart.jpg")
        mock_db.store_cached_image.assert_called_once()
        store_args = mock_db.store_cached_image.call_args[0]
        assert store_args[0] == "1559720"
        assert store_args[1] == "000119312520311265"
        assert store_args[2] == "chart.jpg"
        assert store_args[3] == FAKE_IMAGE

    def test_no_db_adapter_skips_db_entirely(self, mock_http):
        sec = SECClient(http_client=mock_http)  # no db_adapter
        result = sec.fetch_image("1559720", "0001193125-20-311265", "chart.jpg")
        assert result == FAKE_IMAGE  # still works via HTTP

    def test_db_lookup_failure_falls_through_to_sec(self, mock_db, mock_http):
        mock_db.get_cached_image.side_effect = Exception("DB error")
        sec = SECClient(http_client=mock_http, db_adapter=mock_db)
        result = sec.fetch_image("1559720", "0001193125-20-311265", "chart.jpg")
        assert result == FAKE_IMAGE  # fetched from SEC despite DB error

    def test_db_store_failure_still_returns_image(self, mock_db, mock_http):
        mock_db.store_cached_image.side_effect = Exception("DB write error")
        sec = SECClient(http_client=mock_http, db_adapter=mock_db)
        result = sec.fetch_image("1559720", "0001193125-20-311265", "chart.jpg")
        assert result == FAKE_IMAGE  # image returned even if store fails
