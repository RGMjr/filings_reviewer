"""Integration tests for scripts/migrate_onedrive_html_paths.py.

Covers the gh-299 migration: rewriting stale OneDrive paths to worktree-relative
form and populating ``filings.html_content`` from disk (or via SEC re-fetch fallback).

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

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set",
    ),
]

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "migrate_onedrive_html_paths.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location(
        "migrate_onedrive_html_paths_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_onedrive_html_paths_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script_module()


_TEST_CIK = "8888888299"
_TEST_COMPANY_NAME = "OneDrive Migration Test Co"


@pytest.fixture
def test_company(test_db_adapter: DatabaseAdapter) -> int:
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, ticker)
                VALUES (%(cik)s, %(name)s, 'GH299')
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
                """,
                {"cik": _TEST_CIK, "name": _TEST_COMPANY_NAME},
            )
            row = cur.fetchone()
    yield row["company_id"]
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM filings WHERE cik = %(cik)s",
                {"cik": _TEST_CIK},
            )
            cur.execute(
                "DELETE FROM companies WHERE cik = %(cik)s",
                {"cik": _TEST_CIK},
            )


def _insert_filing(
    db: DatabaseAdapter,
    company_id: int,
    accession: str,
    *,
    html_storage_path: str,
    sec_html_url: str | None = "https://www.sec.gov/test/primary.htm",
    html_content: str | None = None,
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
_ONEDRIVE_TEMPLATE = (
    "/Users/testuser/Library/CloudStorage/OneDrive-CMASB/Analytics/"
    "Filings_Analysis/Filings_review_tool/filings_reviewer/{rel}"
)


def test_dry_run_does_not_write(script, test_db_adapter, test_db_url, test_company, tmp_path):
    rel = "data/gold_standard/Foo_Inc/filing.html"
    file_path = tmp_path / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(_BIG_HTML)
    onedrive_path = _ONEDRIVE_TEMPLATE.format(rel=rel)

    fid = _insert_filing(
        test_db_adapter,
        test_company,
        "0000000299-01",
        html_storage_path=onedrive_path,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, html_storage_path, sec_html_url FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )
    counts = script.migrate(
        test_db_adapter, rows, apply=False, sec_user_agent="test", project_root=tmp_path
    )

    assert counts == {
        "audited": 1,
        "rewritten": 1,
        "fetched_from_sec": 0,
        "failed": 0,
    }
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == onedrive_path
    assert after["html_content"] is None


def test_apply_rewrites_and_populates_from_disk(
    script, test_db_adapter, test_db_url, test_company, tmp_path
):
    rel = "data/gold_standard/Bar_Corp/filing.html"
    file_path = tmp_path / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(_BIG_HTML)
    onedrive_path = _ONEDRIVE_TEMPLATE.format(rel=rel)

    fid = _insert_filing(
        test_db_adapter,
        test_company,
        "0000000299-02",
        html_storage_path=onedrive_path,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, html_storage_path, sec_html_url FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )
    counts = script.migrate(
        test_db_adapter, rows, apply=True, sec_user_agent="test", project_root=tmp_path
    )

    assert counts["rewritten"] == 1
    assert counts["fetched_from_sec"] == 0
    assert counts["failed"] == 0
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == rel
    assert after["html_content"] is not None
    assert len(after["html_content"]) >= len(_BIG_HTML) - 5  # encoding may shave bytes


def test_apply_falls_back_to_sec_when_disk_missing(
    script, test_db_adapter, test_db_url, test_company, tmp_path
):
    rel = "data/gold_standard/Missing_Co/filing.html"
    onedrive_path = _ONEDRIVE_TEMPLATE.format(rel=rel)
    sec_url = "https://www.sec.gov/Archives/edgar/data/8888888299/missing.htm"

    fid = _insert_filing(
        test_db_adapter,
        test_company,
        "0000000299-03",
        html_storage_path=onedrive_path,
        sec_html_url=sec_url,
    )
    rows = test_db_adapter.query(
        "SELECT filing_id, html_storage_path, sec_html_url FROM filings WHERE filing_id = %(id)s",
        {"id": fid},
    )

    fetched_text = "<html><body>SEC fallback content " + ("y" * 20_000) + "</body></html>"
    with patch.object(script, "_fetch_via_sec", return_value=fetched_text) as mock_fetch:
        counts = script.migrate(
            test_db_adapter,
            rows,
            apply=True,
            sec_user_agent="test",
            project_root=tmp_path,
        )

    assert counts["fetched_from_sec"] == 1
    assert counts["rewritten"] == 0
    assert counts["failed"] == 0
    mock_fetch.assert_called_once_with(sec_url, "test")
    after = _read_filing(test_db_adapter, fid)
    assert after["html_storage_path"] == rel
    assert after["html_content"] == fetched_text


def test_prod_host_guard_refuses_apply_without_allow_prod(script, monkeypatch, capsys):
    """--apply against a *.neon.tech URL exits 1 without --allow-prod."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@example.neon.tech/db")
    monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)

    with patch.object(sys, "argv", ["migrate_onedrive_html_paths.py", "--apply"]):
        rc = script.main()
    assert rc == 1


def test_prod_host_guard_refuses_apply_without_env_var(script, monkeypatch):
    """--apply --allow-prod against a *.neon.tech URL still requires the env var."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@example.neon.tech/db")
    monkeypatch.delenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", raising=False)

    with patch.object(sys, "argv", ["migrate_onedrive_html_paths.py", "--apply", "--allow-prod"]):
        rc = script.main()
    assert rc == 1


def test_idempotency_second_run_audits_zero(
    script, test_db_adapter, test_db_url, test_company, tmp_path
):
    rel = "data/gold_standard/Idem_Inc/filing.html"
    file_path = tmp_path / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(_BIG_HTML)
    onedrive_path = _ONEDRIVE_TEMPLATE.format(rel=rel)

    _insert_filing(
        test_db_adapter,
        test_company,
        "0000000299-04",
        html_storage_path=onedrive_path,
    )

    # First pass: apply
    rows1 = test_db_adapter.query(
        "SELECT filing_id, html_storage_path, sec_html_url FROM filings "
        "WHERE html_storage_path LIKE '/Users/%%/OneDrive-CMASB/%%' "
        "AND cik = %(cik)s",
        {"cik": _TEST_CIK},
    )
    assert len(rows1) == 1
    counts1 = script.migrate(
        test_db_adapter, rows1, apply=True, sec_user_agent="test", project_root=tmp_path
    )
    assert counts1["rewritten"] == 1

    # Second pass: selector should match nothing
    rows2 = test_db_adapter.query(
        "SELECT filing_id, html_storage_path, sec_html_url FROM filings "
        "WHERE html_storage_path LIKE '/Users/%%/OneDrive-CMASB/%%' "
        "AND cik = %(cik)s",
        {"cik": _TEST_CIK},
    )
    assert rows2 == []
