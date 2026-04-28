"""Pytest configuration and fixtures for extraction_v2 integration tests.

All tests in this directory run with LocalFilesystemStorage regardless of
whether R2_BUCKET is set in the caller's environment. This ensures that
developers who source a prod .env (which sets R2_BUCKET to the prod bucket)
don't hit the R2 prod-write guard during local pytest runs.

The guard itself is intentional and correct — see .claude/rules/infrastructure.md
and src/infra/image_storage.py::R2Storage.put_bytes. This fixture redirects
storage for the test process only; it does not weaken the guard in production.
"""

from __future__ import annotations

import pytest

from src.infra.filing_storage import get_filing_storage
from src.infra.image_storage import get_image_storage


@pytest.fixture(autouse=True)
def _force_local_image_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force image and filing storage to LocalFilesystem* for the test duration.

    When R2_BUCKET is present in the environment (e.g. a developer sourced
    prod .env) but FILINGS_REVIEWER_ALLOW_PROD_WRITES is not set to "1",
    R2Storage.put_bytes / R2FilingStorage.put_bytes raise RuntimeError and
    fail all pipeline tests that write bytes. Clearing the R2 env vars here
    makes these tests deterministic regardless of the caller's shell environment.

    The R2 prod-write guard is preserved — this fixture only redirects storage
    inside the test process via monkeypatch, which is reverted after each test.
    """
    # Clear R2 env vars so the factories return LocalFilesystem*.
    for var in ("R2_BUCKET", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(var, raising=False)

    # Reset both lru_caches so the next call picks up the cleared env.
    get_image_storage.cache_clear()
    get_filing_storage.cache_clear()

    yield

    # Restore cache state on teardown (monkeypatch restores env vars automatically).
    get_image_storage.cache_clear()
    get_filing_storage.cache_clear()
