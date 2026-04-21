"""Tests for src.infra.image_storage — backends + key validation + factory."""

from pathlib import Path

import pytest

from src.infra.image_storage import (
    InvalidStorageKeyError,
    LocalFilesystemStorage,
    R2Storage,
    get_image_storage,
    validate_key,
)


@pytest.fixture(autouse=True)
def _reset_factory_cache():
    get_image_storage.cache_clear()
    # Also clear the image_cache_dir cache (used by LocalFilesystemStorage default).
    from src.infra.paths import image_cache_dir

    image_cache_dir.cache_clear()
    yield
    get_image_storage.cache_clear()
    image_cache_dir.cache_clear()


class TestValidateKey:
    @pytest.mark.parametrize(
        "key",
        [
            "pipeline/0001234567/0001234567-24-000001/g001.jpg",
            "ingestion/42/chart_1.png",
            "a",
            "A_B.C-D/E",
        ],
    )
    def test_accepts_valid_keys(self, key: str) -> None:
        assert validate_key(key) == key

    @pytest.mark.parametrize(
        "key",
        [
            "",
            "/leading-slash",
            "../traversal.jpg",
            "pipeline/../etc/passwd",
            "pipeline/\x00null.jpg",
            "has spaces.jpg",
            "has@at.jpg",
        ],
    )
    def test_rejects_invalid_keys(self, key: str) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_key(key)

    def test_rejects_oversized_key(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_key("a" + ("b" * 600))


class TestLocalFilesystemStorage:
    def test_round_trip(self, tmp_path: Path) -> None:
        storage = LocalFilesystemStorage(tmp_path)
        storage.put_bytes("foo/bar.jpg", b"hello")
        assert storage.get_bytes("foo/bar.jpg") == b"hello"
        assert storage.exists("foo/bar.jpg")

    def test_exists_false_before_put(self, tmp_path: Path) -> None:
        storage = LocalFilesystemStorage(tmp_path)
        assert not storage.exists("nonexistent.jpg")

    def test_get_missing_raises_file_not_found(self, tmp_path: Path) -> None:
        storage = LocalFilesystemStorage(tmp_path)
        with pytest.raises(FileNotFoundError):
            storage.get_bytes("ghost.jpg")

    def test_put_creates_nested_dirs(self, tmp_path: Path) -> None:
        storage = LocalFilesystemStorage(tmp_path)
        storage.put_bytes("a/b/c/d.jpg", b"x")
        assert (tmp_path / "a" / "b" / "c" / "d.jpg").exists()

    def test_invalid_key_rejected(self, tmp_path: Path) -> None:
        storage = LocalFilesystemStorage(tmp_path)
        with pytest.raises(InvalidStorageKeyError):
            storage.put_bytes("../evil.jpg", b"x")


class TestR2Storage:
    """Uses moto's S3 mock — no real R2 calls."""

    @pytest.fixture
    def r2(self, monkeypatch: pytest.MonkeyPatch):
        moto = pytest.importorskip("moto")
        # moto >=5 exposes mock_aws as the unified decorator/ctx.
        # Strip the custom endpoint_url so moto's default S3 interceptor applies.
        import boto3

        original_client = boto3.client

        def patched_client(service, **kwargs):
            kwargs.pop("endpoint_url", None)
            kwargs["region_name"] = "us-east-1"
            return original_client(service, **kwargs)

        monkeypatch.setattr(boto3, "client", patched_client)

        with moto.mock_aws():
            original_client(
                "s3",
                region_name="us-east-1",
                aws_access_key_id="test",
                aws_secret_access_key="test",
            ).create_bucket(Bucket="test-bucket")

            yield R2Storage(
                bucket="test-bucket",
                endpoint="https://example.com",  # stripped by patched_client
                access_key="test",
                secret_key="test",
            )

    def test_round_trip(self, r2: R2Storage) -> None:
        r2.put_bytes("pipeline/cik/acc/g001.jpg", b"chart-bytes")
        assert r2.get_bytes("pipeline/cik/acc/g001.jpg") == b"chart-bytes"

    def test_exists_true_after_put(self, r2: R2Storage) -> None:
        r2.put_bytes("pipeline/cik/acc/g002.jpg", b"x")
        assert r2.exists("pipeline/cik/acc/g002.jpg")

    def test_exists_false_before_put(self, r2: R2Storage) -> None:
        assert not r2.exists("pipeline/cik/acc/never.jpg")

    def test_get_missing_raises_file_not_found(self, r2: R2Storage) -> None:
        with pytest.raises(FileNotFoundError):
            r2.get_bytes("pipeline/cik/acc/ghost.jpg")

    def test_invalid_key_rejected(self, r2: R2Storage) -> None:
        with pytest.raises(InvalidStorageKeyError):
            r2.put_bytes("/leading.jpg", b"x")


class TestGetImageStorageFactory:
    def test_returns_local_when_r2_bucket_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("R2_BUCKET", raising=False)
        monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path))
        storage = get_image_storage()
        assert isinstance(storage, LocalFilesystemStorage)

    def test_returns_r2_when_r2_bucket_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("moto")
        monkeypatch.setenv("R2_BUCKET", "test-bucket")
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test")
        storage = get_image_storage()
        assert isinstance(storage, R2Storage)

    def test_memoized(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("R2_BUCKET", raising=False)
        monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path))
        first = get_image_storage()
        second = get_image_storage()
        assert first is second
