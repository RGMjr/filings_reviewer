"""Model artifact storage backends: local filesystem (dev/test) or R2 (prod).

Selects via ``R2_BUCKET`` env var. When set, :func:`get_model_storage` returns
:class:`R2ModelStorage`; otherwise it falls back to
:class:`LocalFilesystemModelStorage` rooted at :func:`src.infra.paths.model_cache_dir`.

Persists the image-relevance retrain artifacts (model joblib + training CSV +
report) so UI-triggered retrains survive the next Render deploy. ``data/image_model/``
on Render is ephemeral; under ``USE_LEARNED_TRIAGE=true`` an artifact written to
local disk would silently disappear on the next deploy. See gh-391.

Keys (under prefix ``models/image_relevance/``):

  ``models/image_relevance/<run_id>/relevance_model.joblib``
  ``models/image_relevance/<run_id>/model_report.txt``
  ``models/image_relevance/<run_id>/training_data.csv``
  ``models/image_relevance/latest_run_id.txt``        # bare UUID, single writer

The ``latest_run_id.txt`` pointer is written *last* by the retrain wrapper so a
partial upload failure leaves the previous pointer valid. Single-writer is
guaranteed for web-triggered retrains by the concurrency gate at
``src/web/routes/api_unified.py``.

Mirrors :mod:`src.infra.image_storage` and :mod:`src.infra.filing_storage`
exactly; the only differences are the default ``content_type`` and the local
backend's root directory.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from src.infra.image_storage import InvalidStorageKeyError, validate_key  # noqa: F401
from src.infra.paths import model_cache_dir

# Storage layout — single source of truth, imported by both the writer
# (scripts/retrain_image_triage.py) and the reader (src/shared/image_features.py).
MODEL_KEY_PREFIX = "models/image_relevance"
LATEST_POINTER_KEY = f"{MODEL_KEY_PREFIX}/latest_run_id.txt"


def model_key_for_run(run_id: str, filename: str) -> str:
    """Build the per-run storage key for one artifact (joblib / report / csv)."""
    return f"{MODEL_KEY_PREFIX}/{run_id}/{filename}"


class ModelStorage(Protocol):
    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalFilesystemModelStorage:
    """Filesystem backend. Keys map to ``<root>/<key>``."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        validate_key(key)
        return self._root / key

    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise FileNotFoundError(f"Model artifact not found: {key}")
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class R2ModelStorage:
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

    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
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
                raise FileNotFoundError(f"Model artifact not found: {key}") from exc
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
def get_model_storage() -> ModelStorage:
    """Return the active backend. R2 if ``R2_BUCKET`` is set; else local filesystem.

    Callers that mutate ``R2_*`` env vars (tests) must call ``cache_clear()``.
    """
    bucket = os.environ.get("R2_BUCKET")
    if bucket:
        return R2ModelStorage(
            bucket=bucket,
            endpoint=os.environ["R2_ENDPOINT_URL"],
            access_key=os.environ["R2_ACCESS_KEY_ID"],
            secret_key=os.environ["R2_SECRET_ACCESS_KEY"],
        )
    return LocalFilesystemModelStorage(model_cache_dir())
