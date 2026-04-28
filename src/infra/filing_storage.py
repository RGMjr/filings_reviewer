"""Filing HTML storage backends: local filesystem (dev/test) or R2 (prod).

Selects via ``R2_BUCKET`` env var. When set, :func:`get_filing_storage` returns
:class:`R2FilingStorage`; otherwise it falls back to
:class:`LocalFilesystemFilingStorage` rooted at ``<repo>/data/filing_cache/``
(or ``FILING_CACHE_DIR`` override).

``filings.html_storage_path`` stores opaque **storage keys** post-gh-300
(e.g. ``filings/0001234567/0001234567-19-000001/primary.htm``) — never absolute
paths. Key shape is validated via :func:`src.infra.image_storage.validate_key`,
which is shared between filing and image storage.

Mirrors :mod:`src.infra.image_storage` exactly; the only differences are the
default ``content_type='text/html'`` and the local backend's root directory.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from src.infra.image_storage import InvalidStorageKeyError, validate_key  # noqa: F401


class FilingStorage(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str = "text/html") -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


def _filing_cache_root() -> Path:
    override = os.environ.get("FILING_CACHE_DIR")
    if override:
        return Path(override)
    return Path(__file__).parent.parent.parent / "data" / "filing_cache"


class LocalFilesystemFilingStorage:
    """Filesystem backend. Keys map to ``<root>/<key>``."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        validate_key(key)
        return self._root / key

    def put_bytes(self, key: str, data: bytes, content_type: str = "text/html") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise FileNotFoundError(f"Filing not found: {key}")
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class R2FilingStorage:
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

    def put_bytes(self, key: str, data: bytes, content_type: str = "text/html") -> None:
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
                raise FileNotFoundError(f"Filing not found: {key}") from exc
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
def get_filing_storage() -> FilingStorage:
    """Return the active backend. R2 if ``R2_BUCKET`` is set; else local filesystem.

    Callers that mutate ``R2_*`` env vars (tests) must call ``cache_clear()``.
    """
    bucket = os.environ.get("R2_BUCKET")
    if bucket:
        return R2FilingStorage(
            bucket=bucket,
            endpoint=os.environ["R2_ENDPOINT_URL"],
            access_key=os.environ["R2_ACCESS_KEY_ID"],
            secret_key=os.environ["R2_SECRET_ACCESS_KEY"],
        )
    return LocalFilesystemFilingStorage(_filing_cache_root())
