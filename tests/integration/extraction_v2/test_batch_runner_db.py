"""
Integration tests for BatchV2Runner.query_filings() against a real PostgreSQL database.

These tests require a running PostgreSQL database.
Set TEST_DATABASE_URL environment variable to run.

Example:
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \\
        pytest tests/integration/extraction_v2/test_batch_runner_db.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys as _sys
from pathlib import Path
from typing import Any

import pytest

from src.infra.db import DatabaseAdapter

# Skip all tests if no database connection
pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Load batch_v2_extraction script via importlib (it lives in scripts/, not a package)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location(
    "batch_v2_extraction",
    str(_SCRIPTS_DIR / "batch_v2_extraction.py"),
)
assert _spec is not None and _spec.loader is not None, (
    "Could not locate scripts/batch_v2_extraction.py"
)
batch_v2_extraction = importlib.util.module_from_spec(_spec)
# Register before exec so that @dataclass can resolve cls.__module__ lookups.
_sys.modules["batch_v2_extraction"] = batch_v2_extraction
_spec.loader.exec_module(batch_v2_extraction)  # type: ignore[union-attr]

BatchConfig = batch_v2_extraction.BatchConfig
BatchV2Runner = batch_v2_extraction.BatchV2Runner

# Test company constants
_TEST_CIK = "8888888883"
_TEST_COMPANY_NAME = "Batch Test Company"
_TEST_TICKER = "BATC"


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


def _get_test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def db_adapter() -> DatabaseAdapter:
    """Create database adapter for tests."""
    url = _get_test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return DatabaseAdapter(url)


@pytest.fixture(scope="module")
def test_company_id(db_adapter: DatabaseAdapter) -> int:
    """Insert test company and return company_id."""
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, ticker)
                VALUES (%(cik)s, %(name)s, %(ticker)s)
                ON CONFLICT (cik) DO UPDATE
                    SET company_name = EXCLUDED.company_name
                RETURNING company_id
                """,
                {"cik": _TEST_CIK, "name": _TEST_COMPANY_NAME, "ticker": _TEST_TICKER},
            )
            row = cur.fetchone()
    return row["company_id"]  # type: ignore[index]


@pytest.fixture(scope="module")
def runner(db_adapter: DatabaseAdapter) -> Any:
    """Create BatchV2Runner instance using module-default BatchConfig."""
    url = _get_test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    config = BatchConfig()
    return BatchV2Runner(config=config, db_url=url)


# ---------------------------------------------------------------------------
# Autouse function-scoped cleanup -- delete test company filings between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_test_filings(db_adapter: DatabaseAdapter, test_company_id: int) -> Any:
    """Delete all filings for the test company before and after each test."""

    def _delete() -> None:
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM filings WHERE company_id = %(cid)s",
                    {"cid": test_company_id},
                )

    _delete()
    yield
    _delete()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _insert_filing(
    db_adapter: DatabaseAdapter,
    company_id: int,
    accession: str,
    html_storage_path: str | None = None,
) -> int:
    """Insert a filing into the filings table and return filing_id."""
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, cik, accession_number, form_type,
                    filing_date, sec_html_url, html_storage_path
                )
                VALUES (
                    %(company_id)s, %(cik)s, %(accession)s, 'S-1',
                    '2024-01-01', 'https://www.sec.gov/test/' || %(accession)s || '.htm',
                    %(html_path)s
                )
                ON CONFLICT (company_id, accession_number) DO UPDATE
                    SET html_storage_path = EXCLUDED.html_storage_path
                RETURNING filing_id
                """,
                {
                    "company_id": company_id,
                    "cik": _TEST_CIK,
                    "accession": accession,
                    "html_path": html_storage_path,
                },
            )
            row = cur.fetchone()
    return row["filing_id"]  # type: ignore[index]


def _filter_to_test_company(filings: list[dict], company_id: int) -> list[dict]:
    """Filter a list of filing dicts to only those belonging to the test company."""
    return [f for f in filings if f["company_id"] == company_id]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBatchRunnerQueryFilings:
    """Tests for BatchV2Runner.query_filings()."""

    def test_query_filings_returns_expected_columns(
        self,
        db_adapter: DatabaseAdapter,
        test_company_id: int,
        runner: Any,
    ) -> None:
        """query_filings() rows contain the six expected columns."""
        _insert_filing(
            db_adapter,
            test_company_id,
            "8888888883-24-000001",
            html_storage_path="/data/filings/batch_test/filing.html",
        )

        all_filings = runner.query_filings()
        results = _filter_to_test_company(all_filings, test_company_id)

        assert len(results) == 1, "Expected exactly one test-company filing"
        row = results[0]
        expected_keys = {
            "filing_id",
            "accession_number",
            "html_storage_path",
            "company_name",
            "company_id",
            "cik",
        }
        assert expected_keys.issubset(set(row.keys())), (
            f"Missing columns: {expected_keys - set(row.keys())}"
        )

    def test_query_filings_column_values(
        self,
        db_adapter: DatabaseAdapter,
        test_company_id: int,
        runner: Any,
    ) -> None:
        """query_filings() rows contain correct values for inserted filing."""
        html_path = "/data/filings/batch_test/filing_values.html"
        filing_id = _insert_filing(
            db_adapter,
            test_company_id,
            "8888888883-24-000002",
            html_storage_path=html_path,
        )

        all_filings = runner.query_filings()
        results = _filter_to_test_company(all_filings, test_company_id)

        assert len(results) == 1
        row = results[0]
        assert row["filing_id"] == filing_id
        assert row["accession_number"] == "8888888883-24-000002"
        assert row["html_storage_path"] == html_path
        assert row["company_name"] == _TEST_COMPANY_NAME
        assert row["company_id"] == test_company_id
        assert row["cik"] == _TEST_CIK

    def test_query_filings_empty_result(
        self,
        db_adapter: DatabaseAdapter,
        test_company_id: int,
        runner: Any,
    ) -> None:
        """query_filings() returns no rows for the test company when no filings exist."""
        # cleanup_test_filings autouse fixture already removed all filings; insert none
        all_filings = runner.query_filings()
        results = _filter_to_test_company(all_filings, test_company_id)
        assert results == [], f"Expected empty list but got {results}"

    def test_query_filings_null_html_path_still_returned(
        self,
        db_adapter: DatabaseAdapter,
        test_company_id: int,
        runner: Any,
    ) -> None:
        """query_filings() returns filings regardless of html_storage_path being NULL.

        The SQL query has no WHERE clause; all filings are returned and
        html_storage_path=NULL rows are included.
        """
        filing_id = _insert_filing(
            db_adapter,
            test_company_id,
            "8888888883-24-000003",
            html_storage_path=None,
        )

        all_filings = runner.query_filings()
        results = _filter_to_test_company(all_filings, test_company_id)

        assert len(results) == 1
        assert results[0]["filing_id"] == filing_id
        assert results[0]["html_storage_path"] is None

    def test_query_filings_limit(
        self,
        db_adapter: DatabaseAdapter,
        test_company_id: int,
    ) -> None:
        """query_filings() with limit=2 returns at most 2 filings globally.

        Note: the limit is applied in Python after the DB query, so a global
        limit of 2 caps the entire result set.  We insert 5 filings for the
        test company and then verify the limited runner never returns more than
        2 rows in total.
        """
        url = _get_test_db_url()
        if not url:
            pytest.skip("TEST_DATABASE_URL not set")

        for i in range(1, 6):
            _insert_filing(
                db_adapter,
                test_company_id,
                f"8888888883-24-00010{i}",
                html_storage_path=f"/data/filings/batch_test/filing_{i}.html",
            )

        config = BatchConfig(limit=2)
        limited_runner = BatchV2Runner(config=config, db_url=url)
        results = limited_runner.query_filings()

        assert len(results) <= 2, f"Expected at most 2 results with limit=2, got {len(results)}"

    def test_query_filings_resume_from(
        self,
        db_adapter: DatabaseAdapter,
        test_company_id: int,
    ) -> None:
        """query_filings() with resume_from skips filings below the threshold."""
        url = _get_test_db_url()
        if not url:
            pytest.skip("TEST_DATABASE_URL not set")

        # Insert 3 filings and capture their filing_ids in insertion order
        filing_ids: list[int] = []
        for i in range(1, 4):
            fid = _insert_filing(
                db_adapter,
                test_company_id,
                f"8888888883-24-00020{i}",
                html_storage_path=f"/data/filings/batch_test/resume_{i}.html",
            )
            filing_ids.append(fid)

        filing_ids_sorted = sorted(filing_ids)
        # Use the middle filing_id as the resume threshold
        middle_id = filing_ids_sorted[1]

        config = BatchConfig(resume_from=middle_id)
        resume_runner = BatchV2Runner(config=config, db_url=url)

        all_filings = resume_runner.query_filings()
        test_results = _filter_to_test_company(all_filings, test_company_id)
        returned_ids = sorted(r["filing_id"] for r in test_results)

        # Every returned id must be >= resume threshold
        assert all(fid >= middle_id for fid in returned_ids), (
            f"Expected all filing_ids >= {middle_id}, got {returned_ids}"
        )
        # The first (lowest) filing_id should be absent
        assert filing_ids_sorted[0] not in returned_ids, (
            f"filing_id {filing_ids_sorted[0]} should have been skipped by resume_from={middle_id}"
        )
        # The middle and last ids should be present
        assert middle_id in returned_ids
        assert filing_ids_sorted[2] in returned_ids

    def test_query_filings_ordered_by_filing_id(
        self,
        db_adapter: DatabaseAdapter,
        test_company_id: int,
        runner: Any,
    ) -> None:
        """query_filings() returns results ordered by filing_id ascending."""
        for i in range(1, 4):
            _insert_filing(
                db_adapter,
                test_company_id,
                f"8888888883-24-00030{i}",
                html_storage_path=f"/data/filings/batch_test/order_{i}.html",
            )

        all_filings = runner.query_filings()
        test_results = _filter_to_test_company(all_filings, test_company_id)
        ids = [r["filing_id"] for r in test_results]

        assert ids == sorted(ids), f"Expected filing_ids in ascending order, got {ids}"
