"""Tests for src.infra.paths helpers."""

from pathlib import Path

import pytest

from src.infra import paths
from src.infra.paths import image_cache_dir


@pytest.fixture(autouse=True)
def _reset_cache():
    image_cache_dir.cache_clear()
    yield
    image_cache_dir.cache_clear()


class TestImageCacheDir:
    def test_uses_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        override = tmp_path / "custom_cache"
        monkeypatch.setenv("IMAGE_CACHE_DIR", str(override))

        result = image_cache_dir()

        assert result == override
        assert override.exists()

    def test_default_under_repo_data_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IMAGE_CACHE_DIR", raising=False)

        result = image_cache_dir()

        expected_root = Path(paths.__file__).resolve().parents[2] / "data" / "image_cache"
        assert result == expected_root
        assert result.exists()

    def test_creates_missing_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        override = tmp_path / "nested" / "image_cache"
        assert not override.exists()
        monkeypatch.setenv("IMAGE_CACHE_DIR", str(override))

        result = image_cache_dir()

        assert result.exists()
        assert result.is_dir()

    def test_memoized_within_cache_lifetime(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path / "first"))
        first = image_cache_dir()
        monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path / "second"))
        second = image_cache_dir()

        assert first == second
