"""Tests for src.infra.filing_storage — backends + factory.

validate_key is shared with image_storage and tested in test_image_storage.py;
this file covers the filing-specific surface (LocalFilesystemFilingStorage
root, R2FilingStorage prod-write guard, get_filing_storage factory).
"""

from pathlib import Path

import pytest

from src.infra.filing_storage import (
    FilingStorage,
    LocalFilesystemFilingStorage,
    R2FilingStorage,
    get_filing_storage,
)
from src.infra.image_storage import InvalidStorageKeyError


@pytest.fixture(autouse=True)
def _reset_factory_cache():
    get_filing_storage.cache_clear()
    yield
    get_filing_storage.cache_clear()


class TestLocalFilesystemFilingStorage:
    def test_round_trip(self, tmp_path: Path) -> None:
        storage = LocalFilesystemFilingStorage(tmp_path)
        storage.put_bytes("filings/0001234/0001234-19-001/primary.htm", b"<html></html>")
        assert storage.get_bytes("filings/0001234/0001234-19-001/primary.htm") == b"<html></html>"
        assert storage.exists("filings/0001234/0001234-19-001/primary.htm")

    def test_exists_false_before_put(self, tmp_path: Path) -> None:
        storage = LocalFilesystemFilingStorage(tmp_path)
        assert not storage.exists("filings/0001234/0001234-19-001/primary.htm")

    def test_get_missing_raises_file_not_found(self, tmp_path: Path) -> None:
        storage = LocalFilesystemFilingStorage(tmp_path)
        with pytest.raises(FileNotFoundError):
            storage.get_bytes("filings/0001234/0001234-19-001/missing.htm")

    def test_put_creates_nested_dirs(self, tmp_path: Path) -> None:
        storage = LocalFilesystemFilingStorage(tmp_path)
        storage.put_bytes("a/b/c/d.htm", b"x")
        assert (tmp_path / "a" / "b" / "c" / "d.htm").exists()

    def test_invalid_key_rejected(self, tmp_path: Path) -> None:
        storage = LocalFilesystemFilingStorage(tmp_path)
        with pytest.raises(InvalidStorageKeyError):
            storage.put_bytes("../evil.htm", b"x")


class TestR2FilingStorage:
    """Uses moto's S3 mock — no real R2 calls."""

    @pytest.fixture
    def r2(self, monkeypatch: pytest.MonkeyPatch):
        moto = pytest.importorskip("moto")
        import boto3

        original_client = boto3.client

        def patched_client(service, **kwargs):
            kwargs.pop("endpoint_url", None)
            kwargs["region_name"] = "us-east-1"
            return original_client(service, **kwargs)

        monkeypatch.setattr(boto3, "client", patched_client)
        monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "1")

        with moto.mock_aws():
            original_client(
                "s3",
                region_name="us-east-1",
                aws_access_key_id="test",
                aws_secret_access_key="test",
            ).create_bucket(Bucket="test-bucket")

            yield R2FilingStorage(
                bucket="test-bucket",
                endpoint="https://example.com",
                access_key="test",
                secret_key="test",
            )

    def test_round_trip(self, r2: R2FilingStorage) -> None:
        r2.put_bytes("filings/0001234/0001234-19-001/primary.htm", b"<html>body</html>")
        assert r2.get_bytes("filings/0001234/0001234-19-001/primary.htm") == b"<html>body</html>"

    def test_exists_true_after_put(self, r2: R2FilingStorage) -> None:
        r2.put_bytes("filings/0001234/0001234-19-001/x.htm", b"x")
        assert r2.exists("filings/0001234/0001234-19-001/x.htm")

    def test_exists_false_before_put(self, r2: R2FilingStorage) -> None:
        assert not r2.exists("filings/0001234/0001234-19-001/never.htm")

    def test_get_missing_raises_file_not_found(self, r2: R2FilingStorage) -> None:
        with pytest.raises(FileNotFoundError):
            r2.get_bytes("filings/0001234/0001234-19-001/ghost.htm")

    def test_invalid_key_rejected(self, r2: R2FilingStorage) -> None:
        with pytest.raises(InvalidStorageKeyError):
            r2.put_bytes("/leading.htm", b"x")


class TestR2FilingStorageProdWriteGuard:
    @pytest.fixture
    def r2_no_writes_allowed(self, monkeypatch: pytest.MonkeyPatch):
        moto = pytest.importorskip("moto")
        import boto3

        original_client = boto3.client

        def patched_client(service, **kwargs):
            kwargs.pop("endpoint_url", None)
            kwargs["region_name"] = "us-east-1"
            return original_client(service, **kwargs)

        monkeypatch.setattr(boto3, "client", patched_client)
        monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)

        with moto.mock_aws():
            original_client(
                "s3",
                region_name="us-east-1",
                aws_access_key_id="test",
                aws_secret_access_key="test",
            ).create_bucket(Bucket="test-bucket")

            yield R2FilingStorage(
                bucket="test-bucket",
                endpoint="https://example.com",
                access_key="test",
                secret_key="test",
            )

    def test_put_bytes_raises_when_env_var_unset(
        self, r2_no_writes_allowed: R2FilingStorage
    ) -> None:
        with pytest.raises(RuntimeError, match="FILINGS_REVIEWER_ALLOW_PROD_WRITES"):
            r2_no_writes_allowed.put_bytes("filings/cik/acc/primary.htm", b"data")

    def test_put_bytes_raises_when_env_var_not_1(
        self,
        r2_no_writes_allowed: R2FilingStorage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "true")
        with pytest.raises(RuntimeError, match="FILINGS_REVIEWER_ALLOW_PROD_WRITES"):
            r2_no_writes_allowed.put_bytes("filings/cik/acc/primary.htm", b"data")

    def test_get_bytes_allowed_without_env_var(
        self,
        r2_no_writes_allowed: R2FilingStorage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "1")
        r2_no_writes_allowed.put_bytes("filings/cik/acc/r.htm", b"readable")
        monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)
        assert r2_no_writes_allowed.get_bytes("filings/cik/acc/r.htm") == b"readable"

    def test_exists_allowed_without_env_var(
        self,
        r2_no_writes_allowed: R2FilingStorage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "1")
        r2_no_writes_allowed.put_bytes("filings/cik/acc/e.htm", b"x")
        monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)
        assert r2_no_writes_allowed.exists("filings/cik/acc/e.htm") is True


class TestGetFilingStorageFactory:
    def test_returns_local_when_r2_bucket_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("R2_BUCKET", raising=False)
        monkeypatch.setenv("FILING_CACHE_DIR", str(tmp_path))
        storage = get_filing_storage()
        assert isinstance(storage, LocalFilesystemFilingStorage)

    def test_returns_r2_when_r2_bucket_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("moto")
        monkeypatch.setenv("R2_BUCKET", "test-bucket")
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test")
        storage = get_filing_storage()
        assert isinstance(storage, R2FilingStorage)

    def test_memoized(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("R2_BUCKET", raising=False)
        monkeypatch.setenv("FILING_CACHE_DIR", str(tmp_path))
        first = get_filing_storage()
        second = get_filing_storage()
        assert first is second

    def test_local_default_root_when_no_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default root is <repo>/data/filing_cache (no env var)."""
        monkeypatch.delenv("R2_BUCKET", raising=False)
        monkeypatch.delenv("FILING_CACHE_DIR", raising=False)
        storage = get_filing_storage()
        assert isinstance(storage, LocalFilesystemFilingStorage)
        # The root attribute is private but the path should end with data/filing_cache
        assert str(storage._root).endswith("data/filing_cache")  # type: ignore[attr-defined]


class TestProtocolConformance:
    """LocalFilesystemFilingStorage and R2FilingStorage both satisfy FilingStorage."""

    def test_local_satisfies_protocol(self, tmp_path: Path) -> None:
        storage: FilingStorage = LocalFilesystemFilingStorage(tmp_path)
        # If this assignment type-checks at runtime via Protocol, we're good.
        assert hasattr(storage, "put_bytes")
        assert hasattr(storage, "get_bytes")
        assert hasattr(storage, "exists")
