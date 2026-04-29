"""Fixtures for filing_fetcher integration tests.

Patches get_filing_storage to a local tmp dir so that tests which call
fetch_filing work regardless of whether R2_BUCKET is set in the environment.
The test_filing_fetcher_db.py tests only exercise _update_database directly
and don't call get_filing_storage, but test_8k_exhibit_fetch.py does.
"""

from __future__ import annotations

import pytest

from src.infra.filing_storage import LocalFilesystemFilingStorage, get_filing_storage


@pytest.fixture(autouse=True)
def filing_storage(tmp_path, monkeypatch):
    """Patch get_filing_storage to a local tmp dir for filing_fetcher integration tests."""
    get_filing_storage.cache_clear()
    storage = LocalFilesystemFilingStorage(root=tmp_path / "filing_cache")
    monkeypatch.setattr(
        "src.filing_fetcher.filing_fetcher.get_filing_storage",
        lambda: storage,
    )
    yield storage
    get_filing_storage.cache_clear()
