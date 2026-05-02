"""Tests for src.infra.model_storage — backends + factory + prod-write guard.

Mirrors tests/unit/infra/test_image_storage.py. Key validation is reused from
image_storage and tested there; we re-confirm the rejection path in the new
backends so a future refactor can't silently drop it.
"""

from pathlib import Path

import pytest

from src.infra.image_storage import InvalidStorageKeyError
from src.infra.model_storage import (
    LocalFilesystemModelStorage,
    R2ModelStorage,
    get_model_storage,
)


@pytest.fixture(autouse=True)
def _reset_factory_cache():
    get_model_storage.cache_clear()
    from src.infra.paths import model_cache_dir

    model_cache_dir.cache_clear()
    yield
    get_model_storage.cache_clear()
    model_cache_dir.cache_clear()


class TestLocalFilesystemModelStorage:
    def test_round_trip(self, tmp_path: Path) -> None:
        storage = LocalFilesystemModelStorage(tmp_path)
        storage.put_bytes("models/image_relevance/run1/relevance_model.joblib", b"joblib-bytes")
        assert (
            storage.get_bytes("models/image_relevance/run1/relevance_model.joblib")
            == b"joblib-bytes"
        )
        assert storage.exists("models/image_relevance/run1/relevance_model.joblib")

    def test_pointer_file_round_trip(self, tmp_path: Path) -> None:
        """The latest_run_id pointer is just bytes — no special handling."""
        storage = LocalFilesystemModelStorage(tmp_path)
        storage.put_bytes("models/image_relevance/latest_run_id.txt", b"abc-123")
        assert storage.get_bytes("models/image_relevance/latest_run_id.txt") == b"abc-123"

    def test_exists_false_before_put(self, tmp_path: Path) -> None:
        storage = LocalFilesystemModelStorage(tmp_path)
        assert not storage.exists("models/image_relevance/nope.joblib")

    def test_get_missing_raises_file_not_found(self, tmp_path: Path) -> None:
        storage = LocalFilesystemModelStorage(tmp_path)
        with pytest.raises(FileNotFoundError):
            storage.get_bytes("models/image_relevance/ghost.joblib")

    def test_put_creates_nested_dirs(self, tmp_path: Path) -> None:
        storage = LocalFilesystemModelStorage(tmp_path)
        storage.put_bytes("models/image_relevance/uuid-x/relevance_model.joblib", b"x")
        assert (
            tmp_path / "models" / "image_relevance" / "uuid-x" / "relevance_model.joblib"
        ).exists()

    def test_invalid_key_rejected(self, tmp_path: Path) -> None:
        storage = LocalFilesystemModelStorage(tmp_path)
        with pytest.raises(InvalidStorageKeyError):
            storage.put_bytes("../evil.joblib", b"x")


@pytest.fixture
def _moto_s3(monkeypatch: pytest.MonkeyPatch):
    """Boot moto's S3 mock + create a test bucket. Yields nothing — backends create their own client."""
    moto = pytest.importorskip("moto")
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
        ).create_bucket(Bucket="model-test-bucket")
        yield


class TestR2ModelStorage:
    @pytest.fixture
    def r2(self, _moto_s3, monkeypatch: pytest.MonkeyPatch) -> R2ModelStorage:
        monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "1")
        return R2ModelStorage(
            bucket="model-test-bucket",
            endpoint="https://example.com",  # stripped by patched_client
            access_key="test",
            secret_key="test",
        )

    def test_round_trip(self, r2: R2ModelStorage) -> None:
        r2.put_bytes("models/image_relevance/run1/relevance_model.joblib", b"joblib-bytes")
        assert r2.get_bytes("models/image_relevance/run1/relevance_model.joblib") == b"joblib-bytes"

    def test_pointer_file_round_trip(self, r2: R2ModelStorage) -> None:
        r2.put_bytes(
            "models/image_relevance/latest_run_id.txt", b"abc-123", content_type="text/plain"
        )
        assert r2.get_bytes("models/image_relevance/latest_run_id.txt") == b"abc-123"

    def test_exists_true_after_put(self, r2: R2ModelStorage) -> None:
        r2.put_bytes("models/image_relevance/run2/model_report.txt", b"report")
        assert r2.exists("models/image_relevance/run2/model_report.txt")

    def test_exists_false_before_put(self, r2: R2ModelStorage) -> None:
        assert not r2.exists("models/image_relevance/never/relevance_model.joblib")

    def test_get_missing_raises_file_not_found(self, r2: R2ModelStorage) -> None:
        with pytest.raises(FileNotFoundError):
            r2.get_bytes("models/image_relevance/ghost/relevance_model.joblib")

    def test_invalid_key_rejected(self, r2: R2ModelStorage) -> None:
        with pytest.raises(InvalidStorageKeyError):
            r2.put_bytes("/leading.joblib", b"x")


class TestR2ModelStorageProdWriteGuard:
    @pytest.fixture
    def r2_no_writes_allowed(self, _moto_s3, monkeypatch: pytest.MonkeyPatch) -> R2ModelStorage:
        monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)
        return R2ModelStorage(
            bucket="model-test-bucket",
            endpoint="https://example.com",
            access_key="test",
            secret_key="test",
        )

    def test_put_bytes_raises_when_env_var_unset(
        self, r2_no_writes_allowed: R2ModelStorage
    ) -> None:
        with pytest.raises(RuntimeError, match="FILINGS_REVIEWER_ALLOW_PROD_WRITES"):
            r2_no_writes_allowed.put_bytes(
                "models/image_relevance/run1/relevance_model.joblib", b"data"
            )

    def test_put_bytes_raises_when_env_var_not_1(
        self, r2_no_writes_allowed: R2ModelStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "true")
        with pytest.raises(RuntimeError, match="FILINGS_REVIEWER_ALLOW_PROD_WRITES"):
            r2_no_writes_allowed.put_bytes(
                "models/image_relevance/run1/relevance_model.joblib", b"data"
            )

    def test_get_bytes_allowed_without_env_var(
        self, r2_no_writes_allowed: R2ModelStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "1")
        r2_no_writes_allowed.put_bytes("models/image_relevance/run1/read_test.joblib", b"readable")
        monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)
        assert (
            r2_no_writes_allowed.get_bytes("models/image_relevance/run1/read_test.joblib")
            == b"readable"
        )


class TestGetModelStorageFactory:
    def test_returns_local_when_r2_bucket_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("R2_BUCKET", raising=False)
        # model_cache_dir() is path-fixed; we can't override it via env, so we just
        # confirm the type. The actual root is <repo>/data/image_model/, which exists.
        storage = get_model_storage()
        assert isinstance(storage, LocalFilesystemModelStorage)

    def test_returns_r2_when_r2_bucket_set(self, _moto_s3, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("R2_BUCKET", "model-test-bucket")
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test")
        storage = get_model_storage()
        assert isinstance(storage, R2ModelStorage)

    def test_memoized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("R2_BUCKET", raising=False)
        first = get_model_storage()
        second = get_model_storage()
        assert first is second
