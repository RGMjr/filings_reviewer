"""Integration test for scripts/run_v2_extraction.py:resolve_html_path
R2-key short-circuit (gh-300).

Verifies that when ``filings.html_storage_path`` holds an R2 storage key,
``resolve_html_path`` downloads the bytes via the FilingStorage abstraction
and returns a Path pointing at a tempfile populated with those bytes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.infra.filing_storage import LocalFilesystemFilingStorage, get_filing_storage

pytestmark = [pytest.mark.integration]

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_v2_extraction.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("run_v2_extraction_r2_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_v2_extraction_r2_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script_module()


@pytest.fixture
def local_filing_storage(monkeypatch, tmp_path):
    """Force get_filing_storage to a LocalFilesystemFilingStorage rooted at tmp_path."""
    for var in ("R2_BUCKET", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FILING_CACHE_DIR", str(tmp_path / "filing_cache"))
    get_filing_storage.cache_clear()
    yield get_filing_storage()
    get_filing_storage.cache_clear()


def test_resolves_r2_key_to_tempfile(script, local_filing_storage, tmp_path):
    storage: LocalFilesystemFilingStorage = local_filing_storage
    key = "filings/0001234567/0001234567-19-000001/primary.htm"
    payload = b"<html><body>resolved-via-r2</body></html>"
    storage.put_bytes(key, payload)

    filing = {
        "filing_id": 99,
        "company_name": "R2 Resolve Test Co",
        "accession_number": "0001234567-19-000001",
        "html_storage_path": key,
    }
    resolved = script.resolve_html_path(filing)

    assert isinstance(resolved, Path)
    assert resolved.exists()
    assert resolved.read_bytes() == payload
    # Should be a tempfile, not the legacy filesystem-path resolution
    assert str(resolved) != key
    assert ".htm" in resolved.name


def test_falls_back_to_legacy_filesystem_path_when_not_r2_key(
    script, local_filing_storage, tmp_path, monkeypatch
):
    # Place a real file at a legacy data/filings/<accession>/primary.htm path
    accession_clean = "000123456719000003"
    legacy_dir = tmp_path / "data" / "filings" / accession_clean
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = legacy_dir / "primary.htm"
    legacy_path.write_text("legacy")

    # Point script.PROJECT_ROOT at tmp_path so the data/filings fallback resolves.
    monkeypatch.setattr(script, "PROJECT_ROOT", tmp_path)

    filing = {
        "filing_id": 100,
        "company_name": "Legacy Test Co",
        "accession_number": "0001234567-19-000003",
        "html_storage_path": None,  # no R2 key, no storage_path
    }
    resolved = script.resolve_html_path(filing)
    assert resolved == legacy_path
