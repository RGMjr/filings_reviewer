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
    root = Path(override) if override else Path(__file__).resolve().parents[2] / "data" / "image_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root
