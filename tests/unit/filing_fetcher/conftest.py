"""Unit test fixtures for filing_fetcher.

Provides an autouse ``filing_storage`` fixture that patches
``get_filing_storage`` in the fetcher module to use a local tmp dir so that
every test that calls ``fetch_filing`` (or ``fetch_batch``) works without R2
credentials or ``FILINGS_REVIEWER_ALLOW_PROD_WRITES``.
"""

from __future__ import annotations

import pytest

from src.infra.filing_storage import LocalFilesystemFilingStorage, get_filing_storage


@pytest.fixture(autouse=True)
def filing_storage(tmp_path, monkeypatch):
    """Patch get_filing_storage to a local tmp dir for all filing_fetcher unit tests.

    Clears the lru_cache before and after each test so env changes take effect.
    Returns the LocalFilesystemFilingStorage instance so tests that need to
    inspect or manipulate storage can request this fixture explicitly.
    """
    get_filing_storage.cache_clear()
    storage = LocalFilesystemFilingStorage(root=tmp_path / "filing_cache")
    monkeypatch.setattr(
        "src.filing_fetcher.filing_fetcher.get_filing_storage",
        lambda: storage,
    )
    yield storage
    get_filing_storage.cache_clear()
