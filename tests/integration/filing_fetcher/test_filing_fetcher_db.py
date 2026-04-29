"""
Integration tests for FilingFetcher database methods.

These tests require a running PostgreSQL database.
Set TEST_DATABASE_URL environment variable to run.

Example:
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \
        pytest tests/integration/filing_fetcher/test_filing_fetcher_db.py -v
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from datetime import datetime

import pytest

from src.filing_fetcher.filing_fetcher import FilingContent, FilingFetcher
from src.infra.db import DatabaseAdapter

# Skip all tests if no database connection
pytestmark = pytest.mark.integration

TEST_CIK = "8888888884"
TEST_COMPANY_NAME = "Fetcher Test Company"
TEST_TICKER = "FTCH"


def get_test_db_url() -> str | None:
    """Get test database URL from environment."""
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def db_adapter() -> DatabaseAdapter:
    """Create database adapter for tests."""
    url = get_test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return DatabaseAdapter(url)


@pytest.fixture(scope="module")
def test_company_id(db_adapter: DatabaseAdapter) -> int:
    """Create test company, return company_id. Cleaned up at module teardown."""
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, ticker)
                VALUES (%(cik)s, %(name)s, %(ticker)s)
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
                """,
                {"cik": TEST_CIK, "name": TEST_COMPANY_NAME, "ticker": TEST_TICKER},
            )
            row = cur.fetchone()
            return row["company_id"]


@pytest.fixture(scope="module")
def fetcher(db_adapter: DatabaseAdapter) -> FilingFetcher:
    """Create a FilingFetcher with a real db adapter and temp storage root."""
    storage_root = pathlib.Path(tempfile.mkdtemp())
    return FilingFetcher(
        storage_root=str(storage_root),
        user_agent="Test Agent test@example.com",
        db=db_adapter,
    )


# ---------------------------------------------------------------------------
# Per-test cleanup: delete all filings for the test CIK before each test
# so tests start from a clean state.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_test_filings(db_adapter: DatabaseAdapter, test_company_id: int):
    """Delete all filings for the test company before and after each test."""

    def _delete():
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM filings WHERE company_id = %(company_id)s",
                    {"company_id": test_company_id},
                )

    _delete()
    yield
    _delete()


# ---------------------------------------------------------------------------
# Helper: insert a filing row for the test company
# ---------------------------------------------------------------------------


def _insert_filing(
    db_adapter: DatabaseAdapter,
    company_id: int,
    accession_number: str,
    html_storage_path: str | None = None,
    html_fetched_at: str | None = None,
    html_fetch_error: str | None = None,
    is_in_scope_phase1: bool = True,
) -> int:
    """Insert a filing for the test company, return filing_id."""
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO filings (
                    company_id,
                    cik,
                    accession_number,
                    form_type,
                    filing_date,
                    sec_html_url,
                    html_storage_path,
                    html_fetched_at,
                    html_fetch_error,
                    is_in_scope_phase1
                )
                VALUES (
                    %(company_id)s,
                    %(cik)s,
                    %(accession_number)s,
                    'S-1',
                    '2024-01-01',
                    'https://www.sec.gov/Archives/test/filing.htm',
                    %(html_storage_path)s,
                    %(html_fetched_at)s,
                    %(html_fetch_error)s,
                    %(is_in_scope_phase1)s
                )
                RETURNING filing_id
                """,
                {
                    "company_id": company_id,
                    "cik": TEST_CIK,
                    "accession_number": accession_number,
                    "html_storage_path": html_storage_path,
                    "html_fetched_at": html_fetched_at,
                    "html_fetch_error": html_fetch_error,
                    "is_in_scope_phase1": is_in_scope_phase1,
                },
            )
            row = cur.fetchone()
            return row["filing_id"]


# ---------------------------------------------------------------------------
# class TestGetUnfetchedFilings
# ---------------------------------------------------------------------------


class TestGetUnfetchedFilings:
    """Tests for FilingFetcher.get_unfetched_filings()."""

    def test_returns_unfetched_filings(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Only filings with html_fetched_at IS NULL should be returned."""
        # Filing A: unfetched (html_storage_path NULL, html_fetched_at NULL)
        filing_a_id = _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000001",
            html_storage_path=None,
            html_fetched_at=None,
            is_in_scope_phase1=True,
        )
        # Filing B: already fetched
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000002",
            html_storage_path="/some/path.html",
            html_fetched_at="2024-01-15 10:00:00+00",
            is_in_scope_phase1=True,
        )

        results = fetcher.get_unfetched_filings()

        returned_ids = [r["filing_id"] for r in results]
        assert filing_a_id in returned_ids, "Unfetched filing A should be in results"
        # Filing B should not appear (already fetched)
        fetched_ids = {r["filing_id"] for r in results}
        # Query all filings we just inserted to get B's ID
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT filing_id FROM filings WHERE accession_number = '8888888884-24-000002'"
                )
                filing_b_row = cur.fetchone()
        assert filing_b_row["filing_id"] not in fetched_ids, (
            "Filing B (already fetched) must not appear in unfetched results"
        )

    def test_empty_when_all_fetched(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Returns empty list when all in-scope filings have been fetched."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000010",
            html_storage_path="/data/filings/fetched.htm",
            html_fetched_at="2024-01-20 08:00:00+00",
            is_in_scope_phase1=True,
        )

        results = fetcher.get_unfetched_filings()

        # Filter down to only our test company filings in the result
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT filing_id FROM filings WHERE cik = %(cik)s",
                    {"cik": TEST_CIK},
                )
                test_filing_ids = {r["filing_id"] for r in cur.fetchall()}

        overlap = [r for r in results if r["filing_id"] in test_filing_ids]
        assert overlap == [], f"Expected no unfetched test filings, but found: {overlap}"

    def test_excludes_out_of_scope_filings(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Filings with is_in_scope_phase1=false must not be returned."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000020",
            html_storage_path=None,
            html_fetched_at=None,
            is_in_scope_phase1=False,  # out of scope
        )

        results = fetcher.get_unfetched_filings()

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT filing_id FROM filings WHERE accession_number = '8888888884-24-000020'"
                )
                out_of_scope_row = cur.fetchone()

        returned_ids = {r["filing_id"] for r in results}
        assert out_of_scope_row["filing_id"] not in returned_ids, (
            "Out-of-scope filing must not appear in unfetched results"
        )

    def test_returns_expected_fields(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Result rows contain the fields selected by the query."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000030",
            is_in_scope_phase1=True,
        )

        results = fetcher.get_unfetched_filings()

        # Find our specific test filing in results
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT filing_id FROM filings WHERE accession_number = '8888888884-24-000030'"
                )
                our_row = cur.fetchone()

        our_result = next(
            (r for r in results if r["filing_id"] == our_row["filing_id"]),
            None,
        )
        assert our_result is not None, "Our test filing must appear in unfetched results"

        # Check the fields that get_unfetched_filings() SELECTs
        expected_fields = {
            "filing_id",
            "company_id",
            "company_name",
            "cik",
            "accession_number",
            "form_type",
            "filing_date",
            "primary_doc_url",
            "txt_url",
            "processing_status",
            "created_at",
        }
        for field in expected_fields:
            assert field in our_result, f"Expected field '{field}' missing from result row"

        assert our_result["cik"] == TEST_CIK
        assert our_result["company_name"] == TEST_COMPANY_NAME
        assert our_result["accession_number"] == "8888888884-24-000030"


# ---------------------------------------------------------------------------
# class TestUpdateDatabase
# ---------------------------------------------------------------------------


class TestUpdateDatabase:
    """Tests for FilingFetcher._update_database()."""

    def test_update_database_sets_storage_key(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """_update_database() writes the R2 storage key to html_storage_path."""
        filing_id = _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000100",
            is_in_scope_phase1=True,
        )

        content = FilingContent(
            cik=TEST_CIK,
            accession_number="8888888884-24-000100",
            html_path="/data/filings/8888888884/primary.htm",
            txt_path="/data/filings/8888888884/complete.txt",
            fetched_at=datetime(2024, 3, 15, 12, 0, 0),
            html_storage_key="filings/8888888884/8888888884-24-000100/primary.htm",
        )

        result = fetcher._update_database(content, error=None)

        assert result is True, "_update_database should return True on success"

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT html_storage_path, txt_storage_path, html_fetched_at,
                           processing_status, html_fetch_error
                    FROM filings WHERE filing_id = %(filing_id)s
                    """,
                    {"filing_id": filing_id},
                )
                row = cur.fetchone()

        assert row["html_storage_path"] == "filings/8888888884/8888888884-24-000100/primary.htm"
        assert row["txt_storage_path"] == "/data/filings/8888888884/complete.txt"
        assert row["html_fetched_at"] is not None
        assert row["processing_status"] == "fetched"
        assert row["html_fetch_error"] is None

    def test_update_database_idempotent(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Calling _update_database() twice with the same data produces no error."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000101",
            is_in_scope_phase1=True,
        )

        content = FilingContent(
            cik=TEST_CIK,
            accession_number="8888888884-24-000101",
            html_path="/data/filings/idempotent/primary.htm",
            txt_path=None,
            fetched_at=datetime(2024, 4, 1, 9, 30, 0),
            html_storage_key="filings/8888888884/8888888884-24-000101/primary.htm",
        )

        first_result = fetcher._update_database(content, error=None)
        second_result = fetcher._update_database(content, error=None)

        assert first_result is True
        assert second_result is True

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT html_storage_path, processing_status FROM filings "
                    "WHERE accession_number = '8888888884-24-000101'"
                )
                row = cur.fetchone()

        assert row["html_storage_path"] == "filings/8888888884/8888888884-24-000101/primary.htm"
        assert row["processing_status"] == "fetched"

    def test_update_database_clears_previous_error(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """A successful _update_database() clears any prior html_fetch_error."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000102",
            html_fetch_error="Previous connection timeout",
            is_in_scope_phase1=True,
        )

        content = FilingContent(
            cik=TEST_CIK,
            accession_number="8888888884-24-000102",
            html_path="/data/filings/retry/primary.htm",
            fetched_at=datetime(2024, 5, 1, 11, 0, 0),
            html_storage_key="filings/8888888884/8888888884-24-000102/primary.htm",
        )

        fetcher._update_database(content, error=None)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT html_fetch_error FROM filings "
                    "WHERE accession_number = '8888888884-24-000102'"
                )
                row = cur.fetchone()

        assert row["html_fetch_error"] is None, (
            "html_fetch_error should be cleared after a successful fetch"
        )

    def test_update_database_with_resolved_url(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Passing resolved_url updates sec_html_url via COALESCE."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000103",
            is_in_scope_phase1=True,
        )

        content = FilingContent(
            cik=TEST_CIK,
            accession_number="8888888884-24-000103",
            html_path="/data/filings/resolved/primary.htm",
            fetched_at=datetime(2024, 6, 1),
            html_storage_key="filings/8888888884/8888888884-24-000103/primary.htm",
        )
        resolved_url = "https://www.sec.gov/Archives/edgar/data/8888888884/resolved.htm"

        fetcher._update_database(content, error=None, resolved_url=resolved_url)

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sec_html_url FROM filings "
                    "WHERE accession_number = '8888888884-24-000103'"
                )
                row = cur.fetchone()

        assert row["sec_html_url"] == resolved_url


# ---------------------------------------------------------------------------
# class TestUpdateDatabaseError
# ---------------------------------------------------------------------------


class TestUpdateDatabaseError:
    """Tests for FilingFetcher._update_database_error()."""

    def test_update_database_error_records_message(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """_update_database_error() writes the error message to html_fetch_error."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000200",
            is_in_scope_phase1=True,
        )

        error_msg = "Connection timeout after 30 seconds"
        result = fetcher._update_database_error(
            cik=TEST_CIK,
            accession_number="8888888884-24-000200",
            error_msg=error_msg,
        )

        assert result is True, "_update_database_error should return True on success"

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT html_fetch_error FROM filings "
                    "WHERE accession_number = '8888888884-24-000200'"
                )
                row = cur.fetchone()

        assert row["html_fetch_error"] == error_msg

    def test_update_database_error_does_not_overwrite_html_path(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Recording an error must not clear a previously stored html_storage_path."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000201",
            html_storage_path="/data/filings/existing/primary.htm",
            html_fetched_at="2024-01-10 09:00:00+00",
            is_in_scope_phase1=True,
        )

        fetcher._update_database_error(
            cik=TEST_CIK,
            accession_number="8888888884-24-000201",
            error_msg="Retry error",
        )

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT html_storage_path, html_fetch_error FROM filings "
                    "WHERE accession_number = '8888888884-24-000201'"
                )
                row = cur.fetchone()

        # The error is recorded
        assert row["html_fetch_error"] == "Retry error"
        # The existing html_storage_path is untouched
        assert row["html_storage_path"] == "/data/filings/existing/primary.htm"

    def test_update_database_error_idempotent(
        self,
        db_adapter: DatabaseAdapter,
        fetcher: FilingFetcher,
        test_company_id: int,
    ):
        """Calling _update_database_error() twice with the same message is safe."""
        _insert_filing(
            db_adapter,
            test_company_id,
            accession_number="8888888884-24-000202",
            is_in_scope_phase1=True,
        )

        error_msg = "HTTP 404 Not Found"
        fetcher._update_database_error(TEST_CIK, "8888888884-24-000202", error_msg)
        result = fetcher._update_database_error(TEST_CIK, "8888888884-24-000202", error_msg)

        assert result is True

        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT html_fetch_error FROM filings "
                    "WHERE accession_number = '8888888884-24-000202'"
                )
                row = cur.fetchone()

        assert row["html_fetch_error"] == error_msg
