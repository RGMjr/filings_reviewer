"""
Unit tests for the /v2/review/image_crop/<img_id> endpoint.
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


@pytest.fixture()
def app(tmp_path):
    """Create Flask test app with DATA_DIR pointed at tmp_path."""
    flask_app = create_app(
        config_name="testing",
        config_override={"DATABASE_URL": "postgresql://test:test@localhost/test"},
    )
    # Store tmp_path so the security check resolves correctly.
    # The endpoint resolves project_root from current_app.root_path
    # (src/web) → ../../ = project root, then appends "data/".
    # We monkey-patch by stashing the tmp image dir for use in tests.
    flask_app.config["_test_tmp_path"] = tmp_path
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def mock_db():
    return MagicMock()


def _make_test_png(directory: Path, filename: str = "chart.png") -> Path:
    """Create a 20x20 solid-colour PNG in directory and return its path."""
    img = Image.new("RGB", (20, 20), color=(100, 150, 200))
    path = directory / filename
    img.save(str(path), format="PNG")
    return path


# ---------------------------------------------------------------------------
# Helper: build a path that passes the data/ security check
# ---------------------------------------------------------------------------


def _data_dir_from_app_root(app) -> Path:
    """Compute the data/ path the endpoint uses for its security guard."""
    root_path = Path(app.root_path)          # e.g. .../src/web
    project_root = root_path.parent.parent   # e.g. .../filings_reviewer
    return (project_root / "data").resolve()


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestImageCropSuccess:
    def test_returns_200(self, app, client, mock_db, tmp_path):
        data_dir = _data_dir_from_app_root(app)
        data_dir.mkdir(parents=True, exist_ok=True)
        img_path = _make_test_png(data_dir, "test_chart.png")

        mock_db.query.return_value = [{"file_path": str(img_path)}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/test-img-001?x=0&y=0&w=10&h=10")

        assert resp.status_code == 200

    def test_content_type_is_png(self, app, client, mock_db):
        data_dir = _data_dir_from_app_root(app)
        data_dir.mkdir(parents=True, exist_ok=True)
        img_path = _make_test_png(data_dir, "test_chart2.png")

        mock_db.query.return_value = [{"file_path": str(img_path)}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/test-img-002?x=0&y=0&w=10&h=10")

        assert resp.content_type.startswith("image/png")

    def test_response_body_is_valid_png(self, app, client, mock_db):
        data_dir = _data_dir_from_app_root(app)
        data_dir.mkdir(parents=True, exist_ok=True)
        img_path = _make_test_png(data_dir, "test_chart3.png")

        mock_db.query.return_value = [{"file_path": str(img_path)}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/test-img-003?x=0&y=0&w=10&h=10")

        assert len(resp.data) > 0
        # Verify it's a valid PNG by parsing it
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

    def test_path_outside_data_dir_returns_404(self, app, client, mock_db, tmp_path):
        # Point to a file outside the project's data/ directory
        outside_path = tmp_path / "evil.png"
        _make_test_png(tmp_path, "evil.png")

        mock_db.query.return_value = [{"file_path": str(outside_path)}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/img-evil?x=0&y=0&w=10&h=10")
        assert resp.status_code == 404

    def test_nonexistent_file_returns_404(self, app, client, mock_db):
        data_dir = _data_dir_from_app_root(app)
        missing = data_dir / "does_not_exist.png"

        mock_db.query.return_value = [{"file_path": str(missing)}]
        with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
            resp = client.get("/v2/review/image_crop/img-missing?x=0&y=0&w=10&h=10")
        assert resp.status_code == 404
