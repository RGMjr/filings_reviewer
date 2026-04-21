"""
Unit tests for the /v2/review/image_crop/<img_id> endpoint.

Post-R2 migration: `v2_image_assets.file_path` stores opaque storage keys
(e.g. `pipeline/<cik>/<accession>/<filename>`), not absolute paths. These
tests run against the LocalFilesystemStorage backend rooted at tmp_path,
so pytest never touches the real `data/image_cache/` tree.
"""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_image_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Route LocalFilesystemStorage under tmp_path for every test in this module."""
    from src.infra.image_storage import get_image_storage
    from src.infra.paths import image_cache_dir

    monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("R2_BUCKET", raising=False)
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()
    yield
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()


@pytest.fixture()
def app():
    flask_app = create_app(
        config_name="testing",
        config_override={"DATABASE_URL": "postgresql://test:test@localhost/test"},
    )
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def mock_db():
    return MagicMock()


def _make_png_bytes() -> bytes:
    """Return bytes of a 20x20 solid-colour PNG."""
    img = Image.new("RGB", (20, 20), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def seed_image():
    """Factory that uploads a PNG to storage under a given key and returns the key."""
    from src.infra.image_storage import get_image_storage

    def _factory(key: str) -> str:
        get_image_storage().put_bytes(key, _make_png_bytes(), content_type="image/png")
        return key

    return _factory


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestImageCropSuccess:
    def test_returns_200(self, client, mock_db, seed_image):
        key = seed_image("pipeline/1234567/acc-001/chart.png")
        mock_db.query.return_value = [{"file_path": key}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/test-img-001?x=0&y=0&w=10&h=10")
        assert resp.status_code == 200

    def test_content_type_is_png(self, client, mock_db, seed_image):
        key = seed_image("pipeline/1234567/acc-002/chart.png")
        mock_db.query.return_value = [{"file_path": key}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/test-img-002?x=0&y=0&w=10&h=10")
        assert resp.content_type.startswith("image/png")

    def test_cache_control_header_set(self, client, mock_db, seed_image):
        key = seed_image("pipeline/1234567/acc-003/chart.png")
        mock_db.query.return_value = [{"file_path": key}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/test-img-003?x=0&y=0&w=10&h=10")
        assert "max-age" in resp.headers.get("Cache-Control", "")

    def test_response_body_is_valid_png(self, client, mock_db, seed_image):
        key = seed_image("pipeline/1234567/acc-004/chart.png")
        mock_db.query.return_value = [{"file_path": key}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/test-img-004?x=0&y=0&w=10&h=10")
        assert len(resp.data) > 0
        parsed = Image.open(io.BytesIO(resp.data))
        assert parsed.format == "PNG"
        assert parsed.size == (10, 10)


# ---------------------------------------------------------------------------
# 404 paths
# ---------------------------------------------------------------------------


class TestImageCrop404:
    def test_unknown_img_id_returns_404(self, client, mock_db):
        mock_db.query.return_value = []
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/no-such-id?x=0&y=0&w=10&h=10")
        assert resp.status_code == 404

    def test_null_file_path_returns_404(self, client, mock_db):
        mock_db.query.return_value = [{"file_path": None}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/img-null-path?x=0&y=0&w=10&h=10")
        assert resp.status_code == 404

    def test_invalid_storage_key_returns_404(self, client, mock_db):
        """Legacy absolute-path rows fail validate_key and return 404 (not 500)."""
        mock_db.query.return_value = [{"file_path": "/var/folders/tmpdir/legacy.jpg"}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/img-legacy?x=0&y=0&w=10&h=10")
        assert resp.status_code == 404

    def test_nonexistent_file_returns_404(self, client, mock_db):
        """Valid-shape key but no object in storage."""
        mock_db.query.return_value = [{"file_path": "pipeline/9999999/missing-acc/ghost.png"}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/img-missing?x=0&y=0&w=10&h=10")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth (KNOWN_ISSUES #48): image_crop is guarded by require_api_key.
# Existing fixtures above use TestingConfig (API_KEY_REQUIRED=False); these
# tests build an app with the guard active.
# ---------------------------------------------------------------------------


class TestImageCropAuth:
    @pytest.fixture()
    def authed_app(self):
        return create_app(
            config_name="testing",
            config_override={
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "API_KEY_REQUIRED": True,
                "API_KEY": "test-key",
            },
        )

    @pytest.fixture()
    def authed_client(self, authed_app):
        return authed_app.test_client()

    def test_missing_api_key_returns_401(self, authed_client, mock_db):
        """No X-API-Key, no same-origin headers — external fetch is rejected."""
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = authed_client.get("/v2/review/image_crop/any-img?x=0&y=0&w=10&h=10")
        assert resp.status_code == 401
        mock_db.query.assert_not_called()

    def test_wrong_api_key_returns_401(self, authed_client, mock_db):
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = authed_client.get(
                "/v2/review/image_crop/any-img?x=0&y=0&w=10&h=10",
                headers={"X-API-Key": "not-the-key"},
            )
        assert resp.status_code == 401
        mock_db.query.assert_not_called()

    def test_correct_api_key_returns_200(self, authed_client, mock_db, seed_image):
        key = seed_image("pipeline/1234567/auth-001/chart.png")
        mock_db.query.return_value = [{"file_path": key}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = authed_client.get(
                "/v2/review/image_crop/auth-img-001?x=0&y=0&w=10&h=10",
                headers={"X-API-Key": "test-key"},
            )
        assert resp.status_code == 200
        assert resp.content_type.startswith("image/png")

    def test_same_origin_referer_bypass_returns_200(
        self, authed_client, mock_db, seed_image
    ):
        """Embedded <img src="..."> inside a review page carries a matching Referer."""
        key = seed_image("pipeline/1234567/auth-002/chart.png")
        mock_db.query.return_value = [{"file_path": key}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            # Flask test client default host is localhost; Referer must start with host_url.
            resp = authed_client.get(
                "/v2/review/image_crop/auth-img-002?x=0&y=0&w=10&h=10",
                headers={"Referer": "http://localhost/v2/review/filings"},
            )
        assert resp.status_code == 200

    def test_api_key_required_but_unset_returns_500(self, mock_db):
        """API_KEY_REQUIRED=True but API_KEY not configured is a server misconfig."""
        app = create_app(
            config_name="testing",
            config_override={
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "API_KEY_REQUIRED": True,
                "API_KEY": None,
            },
        )
        client = app.test_client()
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get(
                "/v2/review/image_crop/any-img?x=0&y=0&w=10&h=10",
                headers={"X-API-Key": "anything"},
            )
        assert resp.status_code == 500
