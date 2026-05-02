"""Project path helpers."""

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def image_cache_dir() -> Path:
    """Return the persistent image-cache root, creating it on first access.

    Honors the ``IMAGE_CACHE_DIR`` env var (used by Render deployments with a
    mounted disk). Otherwise falls back to ``<repo>/data/image_cache/``. Tests
    that mutate the env var must call ``image_cache_dir.cache_clear()``.
    """
    override = os.environ.get("IMAGE_CACHE_DIR")
    root = (
        Path(override) if override else Path(__file__).resolve().parents[2] / "data" / "image_cache"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


@lru_cache(maxsize=1)
def model_cache_dir() -> Path:
    """Return the model-artifact cache root, creating it on first access.

    Used by :mod:`src.infra.model_storage` as the local backend root and by
    :func:`src.shared.image_features._load_model` as the materialization
    scratch directory (``_cache/<run_id>/``) when R2 is the source of truth.
    No env-var override — the path is fixed at ``<repo>/data/image_model/`` so
    Render's ephemeral disk semantics are explicit.
    """
    root = Path(__file__).resolve().parents[2] / "data" / "image_model"
    root.mkdir(parents=True, exist_ok=True)
    return root
