"""Integration tests for scripts/migrate_filing_html_to_r2.py.

Covers the gh-300 migration: uploads filing HTML to R2 (via
LocalFilesystemFilingStorage in tests) and rewrites
``filings.html_storage_path`` from filesystem path to opaque storage key.

Requires TEST_DATABASE_URL.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.infra.db import DatabaseAdapter
from src.infra.filing_storage import LocalFilesystemFilingStorage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set",
    ),
]

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "migrate_filing_html_to_r2.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location(
        "migrate_filing_html_to_r2_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_filing_html_to_r2_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script_module()


_TEST_CIK = "8888888300"
_TEST_COMPANY_NAME = "R2 Migration Test Co"


@pytest.fixture
def test_company(test_db_adapter: DatabaseAdapter) -> int:
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, ticker)
                VALUES (%(cik)s, %(name)s, 'GH300')
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
                """,
                {"cik": _TEST_CIK, "name": _TEST_COMPANY_NAME},
            )
            row = cur.fetchone()
    yield row["company_id"]
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM filings WHERE cik = %(cik)s", {"cik": _TEST_CIK})
            cur.execute("DELETE FROM companies WHERE cik = %(cik)s", {"cik": _TEST_CIK})


def _insert_filing(
    db: DatabaseAdapter,
    company_id: int,
    accession: str,
    *,
    html_storage_path: str | None,
    html_content: str | None,
    sec_html_url: str | None = "https://www.sec.gov/test/primary.htm",
) -> int:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, cik, accession_number, form_type,
                    filing_date, sec_html_url, html_storage_path, html_content
                ) VALUES (
                    %(company_id)s, %(cik)s, %(acc)s, 'S-1',
                    '2024-01-01', %(sec_url)s, %(path)s, %(content)s
                )
                RETURNING filing_id
                """,
                {
                    "company_id": company_id,
                    "cik": _TEST_CIK,
                    "acc": accession,
                    "sec_url": sec_html_url,
                    "path": html_storage_path,
                    "content": html_content,
                },
            )
            return cur.fetchone()["filing_id"]


def _read_filing(db: DatabaseAdapter, filing_id: int) -> dict:
    rows = db.query(
        "SELECT html_storage_path, html_content FROM filings WHERE filing_id = %(id)s",
        {"id": filing_id},
    )
    return rows[0]


_BIG_HTML = "<html><body>" + ("x" * 20_000) + "</body></html>"


def _local_storage(tmp_path: Path) -> LocalFilesystemFilingStorage:
    return LocalFilesystemFilingStorage(tmp_path / "filing_cache")


def test_dry_run_does_not_write(script, test_db_adapter, test_company, tmp_path):
    storage = _local_storage(tmp_path)
    accession = "0000000300-01"
    fid = _insert_filing(
        test_db_adapter,
        test_company,
        accession,
        html_storage_path="data/filings/x/y/primary.htm",
        html_content=_BIG_HTML,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, cik, accession_number, html_storage_path, html_content, sec_html_url "
        "FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )

    counts = script.migrate(test_db_adapter, rows, storage, apply=False, sec_user_agent="test")

    assert counts == {
        "audited": 1,
        "migrated": 1,
        "sec_fetched": 0,
        "skipped": 0,
        "failed": 0,
    }
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == "data/filings/x/y/primary.htm"
    assert not storage.exists(f"filings/{_TEST_CIK}/{accession}/primary.htm")


def test_apply_uploads_from_html_content_and_rewrites_path(
    script, test_db_adapter, test_company, tmp_path
):
    storage = _local_storage(tmp_path)
    accession = "0000000300-02"
    fid = _insert_filing(
        test_db_adapter,
        test_company,
        accession,
        html_storage_path="data/filings/legacy/path/primary.htm",
        html_content=_BIG_HTML,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, cik, accession_number, html_storage_path, html_content, sec_html_url "
        "FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )

    counts = script.migrate(test_db_adapter, rows, storage, apply=True, sec_user_agent="test")

    assert counts["migrated"] == 1
    assert counts["failed"] == 0
    expected_key = f"filings/{_TEST_CIK}/{accession}/primary.htm"
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == expected_key
    assert after["html_content"] is not None  # column NOT cleared per plan decision #3
    assert storage.exists(expected_key)
    assert storage.get_bytes(expected_key) == _BIG_HTML.encode("utf-8")


def test_apply_falls_back_to_disk_when_html_content_missing(
    script, test_db_adapter, test_company, tmp_path, monkeypatch
):
    storage = _local_storage(tmp_path)
    accession = "0000000300-03"
    rel_path = "data/filings/diskonly/foo/primary.htm"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(_BIG_HTML)
    fid = _insert_filing(
        test_db_adapter,
        test_company,
        accession,
        html_storage_path=rel_path,
        html_content=None,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, cik, accession_number, html_storage_path, html_content, sec_html_url "
        "FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )

    # Pass tmp_path as project_root so relative html_storage_path resolves there.
    counts = script.migrate(
        test_db_adapter,
        rows,
        storage,
        apply=True,
        sec_user_agent="test",
        project_root=tmp_path,
    )

    assert counts["migrated"] == 1
    assert counts["failed"] == 0
    expected_key = f"filings/{_TEST_CIK}/{accession}/primary.htm"
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == expected_key
    assert storage.get_bytes(expected_key) == _BIG_HTML.encode("utf-8")


def test_apply_falls_back_to_sec_when_disk_and_content_missing(
    script, test_db_adapter, test_company, tmp_path
):
    storage = _local_storage(tmp_path)
    accession = "0000000300-04"
    sec_url = "https://www.sec.gov/Archives/edgar/data/8888888300/missing.htm"
    fid = _insert_filing(
        test_db_adapter,
        test_company,
        accession,
        html_storage_path="data/filings/missing/primary.htm",
        html_content=None,
        sec_html_url=sec_url,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, cik, accession_number, html_storage_path, html_content, sec_html_url "
        "FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )

    fetched = b"<html>SEC body" + (b"y" * 20_000) + b"</html>"
    with patch.object(script, "_fetch_via_sec", return_value=fetched) as mock_fetch:
        counts = script.migrate(
            test_db_adapter,
            rows,
            storage,
            apply=True,
            sec_user_agent="test",
            project_root=tmp_path,
        )

    assert counts["sec_fetched"] == 1
    assert counts["migrated"] == 1
    assert counts["failed"] == 0
    mock_fetch.assert_called_once_with(sec_url, "test")
    expected_key = f"filings/{_TEST_CIK}/{accession}/primary.htm"
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == expected_key
    assert storage.get_bytes(expected_key) == fetched


def test_skipped_when_no_source_available(script, test_db_adapter, test_company, tmp_path):
    storage = _local_storage(tmp_path)
    accession = "0000000300-05"
    fid = _insert_filing(
        test_db_adapter,
        test_company,
        accession,
        html_storage_path="data/filings/none/primary.htm",
        html_content=None,
        sec_html_url=None,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, cik, accession_number, html_storage_path, html_content, sec_html_url "
        "FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )

    counts = script.migrate(
        test_db_adapter,
        rows,
        storage,
        apply=True,
        sec_user_agent="test",
        project_root=tmp_path,
    )

    assert counts["skipped"] == 1
    assert counts["migrated"] == 0
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == "data/filings/none/primary.htm"


def test_prod_host_guard_refuses_apply_without_allow_prod(script, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@example.neon.tech/db")
    monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)
    with patch.object(sys, "argv", ["migrate_filing_html_to_r2.py", "--apply"]):
        rc = script.main()
    assert rc == 1


def test_prod_host_guard_refuses_apply_without_env_var(script, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@example.neon.tech/db")
    monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)
    with patch.object(sys, "argv", ["migrate_filing_html_to_r2.py", "--apply", "--allow-prod"]):
        rc = script.main()
    assert rc == 1


def test_idempotency_second_run_audits_zero(script, test_db_adapter, test_company, tmp_path):
    storage = _local_storage(tmp_path)
    accession = "0000000300-06"
    fid = _insert_filing(
        test_db_adapter,
        test_company,
        accession,
        html_storage_path="data/filings/idem/primary.htm",
        html_content=_BIG_HTML,
    )

    # First pass: apply (use the same selector the script's main() would use)
    selector = (
        "SELECT filing_id, cik, accession_number, html_storage_path, html_content, sec_html_url "
        "FROM filings WHERE html_storage_path IS NOT NULL "
        "AND html_storage_path NOT LIKE 'filings/%%/%%/%%' AND cik = %(cik)s"
    )
    rows1 = test_db_adapter.query(selector, {"cik": _TEST_CIK})
    assert len(rows1) == 1
    counts1 = script.migrate(test_db_adapter, rows1, storage, apply=True, sec_user_agent="test")
    assert counts1["migrated"] == 1

    # Second pass: selector should match nothing
    rows2 = test_db_adapter.query(selector, {"cik": _TEST_CIK})
    assert rows2 == []

    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"].startswith("filings/")
