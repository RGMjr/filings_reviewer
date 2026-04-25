"""Image storage backends: local filesystem (dev/test) or S3-compatible (R2/prod).

Selects via ``R2_BUCKET`` env var. When set, :func:`get_image_storage` returns
an :class:`R2Storage` client pointed at Cloudflare R2; otherwise it falls back
to :class:`LocalFilesystemStorage` rooted at :func:`src.infra.paths.image_cache_dir`.

``v2_image_assets.file_path`` stores opaque **storage keys** (e.g.
``pipeline/0001234567/0001234567-24-000001/g001.jpg``) — never absolute paths.
Key shape is validated at every call via :func:`validate_key`.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from src.infra.paths import image_cache_dir

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]{0,511}$")


class InvalidStorageKeyError(ValueError):
    """Raised when a storage key fails shape validation."""


def validate_key(key: str) -> str:
    """Reject keys with traversal segments, leading slash, or disallowed chars."""
    if not isinstance(key, str) or not _KEY_RE.match(key) or ".." in key:
        raise InvalidStorageKeyError(f"Invalid storage key: {key!r}")
    return key


class ImageStorage(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalFilesystemStorage:
    """Filesystem backend. Keys map to ``<root>/<key>``."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        validate_key(key)
        return self._root / key

    def put_bytes(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise FileNotFoundError(f"Image not found: {key}")
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class R2Storage:
    """Cloudflare R2 (S3-compatible) backend."""

    def __init__(self, bucket: str, endpoint: str, access_key: str, secret_key: str) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            region_name="auto",
        )

    def put_bytes(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        if os.environ.get("FILINGS_REVIEWER_ALLOW_PROD_WRITES") != "1":
            raise RuntimeError(
                "Refusing R2 write — set FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 to allow. "
                "This guard prevents accidental prod R2 mutations when running CLI tools "
                "with prod credentials in the environment."
            )
        validate_key(key)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        validate_key(key)
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"Image not found: {key}") from exc
            raise
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        validate_key(key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise


@lru_cache(maxsize=1)
def get_image_storage() -> ImageStorage:
    """Return the active backend. R2 if ``R2_BUCKET`` is set; else local filesystem.

    Callers that mutate ``R2_*`` env vars (tests) must call ``cache_clear()``.
    """
    bucket = os.environ.get("R2_BUCKET")
    if bucket:
        return R2Storage(
            bucket=bucket,
            endpoint=os.environ["R2_ENDPOINT_URL"],
            access_key=os.environ["R2_ACCESS_KEY_ID"],
            secret_key=os.environ["R2_SECRET_ACCESS_KEY"],
        )
    return LocalFilesystemStorage(image_cache_dir())
