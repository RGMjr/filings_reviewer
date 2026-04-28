"""
Unit tests for the image cache proxy route.

GET /images/cache/<cik>/<accession_no>/<filename>
"""

from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


@pytest.fixture
def app():
    return create_app(
        config_name="testing",
        config_override={"DATABASE_URL": "postgresql://test:test@localhost/test"},
    )


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    return MagicMock()


FAKE_IMAGE = b"\xff\xd8\xff\xe0"
CIK = "1559720"
ACCESSION = "000119312520311265"
FILENAME = "chart.jpg"
ROUTE = f"/images/cache/{CIK}/{ACCESSION}/{FILENAME}"


class TestImageCacheRouteHit:
    def test_returns_200_on_cache_hit(self, client, mock_db):
        mock_db.get_cached_image.return_value = {
            "image_data": FAKE_IMAGE,
            "content_type": "image/jpeg",
            "size_bytes": len(FAKE_IMAGE),
        }
        with patch("src.web.routes.image_cache.get_db", return_value=mock_db):
            resp = client.get(ROUTE)
        assert resp.status_code == 200

    def test_returns_image_bytes_on_hit(self, client, mock_db):
        mock_db.get_cached_image.return_value = {
            "image_data": FAKE_IMAGE,
            "content_type": "image/jpeg",
            "size_bytes": len(FAKE_IMAGE),
        }
        with patch("src.web.routes.image_cache.get_db", return_value=mock_db):
            resp = client.get(ROUTE)
        assert resp.data == FAKE_IMAGE

    def test_sets_cache_control_header(self, client, mock_db):
        mock_db.get_cached_image.return_value = {
            "image_data": FAKE_IMAGE,
            "content_type": "image/jpeg",
            "size_bytes": len(FAKE_IMAGE),
        }
        with patch("src.web.routes.image_cache.get_db", return_value=mock_db):
            resp = client.get(ROUTE)
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")

    def test_uses_stored_content_type(self, client, mock_db):
        mock_db.get_cached_image.return_value = {
            "image_data": b"\x89PNG\r\n",
            "content_type": "image/png",
            "size_bytes": 6,
        }
        with patch("src.web.routes.image_cache.get_db", return_value=mock_db):
            resp = client.get(f"/images/cache/{CIK}/{ACCESSION}/chart.png")
        assert resp.content_type.startswith("image/png")

    def test_no_api_key_required(self, client, mock_db):
        """Route must be accessible without API key (images load via <img> tags)."""
        mock_db.get_cached_image.return_value = {
            "image_data": FAKE_IMAGE,
            "content_type": "image/jpeg",
            "size_bytes": len(FAKE_IMAGE),
        }
        with patch("src.web.routes.image_cache.get_db", return_value=mock_db):
            resp = client.get(ROUTE)
        assert resp.status_code == 200


class TestImageCacheRouteMiss:
    def test_fetches_from_sec_on_cache_miss(self, client, mock_db):
        mock_db.get_cached_image.return_value = None
        mock_sec = MagicMock()
        mock_sec.fetch_image.return_value = FAKE_IMAGE
        with (
            patch("src.web.routes.image_cache.get_db", return_value=mock_db),
            patch("src.web.routes.image_cache.SECClient", return_value=mock_sec),
        ):
            resp = client.get(ROUTE)
        assert resp.status_code == 200
        # The URL path carries the dashes-stripped 18-digit form, but
        # SECClient.fetch_image extracts via SEC_ACCESSION_PATTERN which
        # requires dashes — the route must reinsert them. (Regression
        # guard for PR #244 / gh-image-cache-proxy-404.)
        mock_sec.fetch_image.assert_called_once_with(
            cik=CIK,
            accession_number="0001193125-20-311265",
            filename=FILENAME,
        )

    def test_passes_through_non_18_digit_accession(self, client, mock_db):
        """Non-canonical accession path is forwarded as-is so fetch_image's
        own warning + 404 path still surfaces (no silent reformatting)."""
        mock_db.get_cached_image.return_value = None
        mock_sec = MagicMock()
        mock_sec.fetch_image.return_value = None
        weird_acc = "not-an-accession"
        with (
            patch("src.web.routes.image_cache.get_db", return_value=mock_db),
            patch("src.web.routes.image_cache.SECClient", return_value=mock_sec),
        ):
            resp = client.get(f"/images/cache/{CIK}/{weird_acc}/{FILENAME}")
        assert resp.status_code == 404
        mock_sec.fetch_image.assert_called_once_with(
            cik=CIK,
            accession_number=weird_acc,
            filename=FILENAME,
        )

    def test_returns_404_when_sec_fetch_fails(self, client, mock_db):
        mock_db.get_cached_image.return_value = None
        mock_sec = MagicMock()
        mock_sec.fetch_image.return_value = None  # SEC fetch failed
        with (
            patch("src.web.routes.image_cache.get_db", return_value=mock_db),
            patch("src.web.routes.image_cache.SECClient", return_value=mock_sec),
        ):
            resp = client.get(ROUTE)
        assert resp.status_code == 404

    def test_infers_content_type_from_filename(self, client, mock_db):
        mock_db.get_cached_image.return_value = None
        mock_sec = MagicMock()
        mock_sec.fetch_image.return_value = b"\x89PNG\r\n"
        with (
            patch("src.web.routes.image_cache.get_db", return_value=mock_db),
            patch("src.web.routes.image_cache.SECClient", return_value=mock_sec),
        ):
            resp = client.get(f"/images/cache/{CIK}/{ACCESSION}/chart.png")
        assert resp.content_type.startswith("image/png")

    def test_sec_client_created_with_db_adapter(self, client, mock_db):
        mock_db.get_cached_image.return_value = None
        mock_sec = MagicMock()
        mock_sec.fetch_image.return_value = FAKE_IMAGE
        mock_sec_class = MagicMock(return_value=mock_sec)
        with (
            patch("src.web.routes.image_cache.get_db", return_value=mock_db),
            patch("src.web.routes.image_cache.SECClient", mock_sec_class),
        ):
            client.get(ROUTE)
        _, kwargs = mock_sec_class.call_args
        assert kwargs.get("db_adapter") is mock_db
