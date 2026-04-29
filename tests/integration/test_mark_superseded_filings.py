"""Integration tests for DatabaseAdapter.mark_superseded_filings (legacy-040).

Two scopes are validated:

1. S-1/F-1 chain: latest by filing_date wins per company.
2. 10-K/10-K/A chain: latest by filing_date wins per (company, fiscal year),
   so cross-fiscal-year 10-Ks remain in scope while only the amended-year
   original is demoted by its 10-K/A.
"""

from __future__ import annotations

from src.infra.db import DatabaseAdapter
from tests.integration.conftest import create_test_company


def _upsert(
    db: DatabaseAdapter,
    company_id: int,
    cik: str,
    accession_number: str,
    form_type: str,
    filing_date: str,
    period_end_date: str | None = None,
) -> int:
    return db.upsert_filing(
        company_id=company_id,
        cik=cik,
        accession_number=accession_number,
        form_type=form_type,
        filing_date=filing_date,
        period_end_date=period_end_date,
        sec_html_url=f"https://www.sec.gov/test/{accession_number}",
        is_in_scope_phase1=True,
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )


def _is_in_scope(db: DatabaseAdapter, filing_id: int) -> bool:
    rows = db.query(
        "SELECT is_in_scope_phase1 FROM filings WHERE filing_id = %(fid)s",
        {"fid": filing_id},
    )
    return bool(rows[0]["is_in_scope_phase1"])


class TestS1F1Supersession:
    def test_latest_s1_amendment_wins_per_company(self, clean_db: DatabaseAdapter) -> None:
        """Original S-1 demoted; latest S-1/A kept. Pre-existing semantics."""
        company_id = create_test_company(clean_db, cik="0000000111", company_name="S1 Co")

        original = _upsert(
            clean_db,
            company_id,
            "0000000111",
            "0000000111-24-000001",
            "S-1",
            "2024-01-10",
        )
        amendment = _upsert(
            clean_db,
            company_id,
            "0000000111",
            "0000000111-24-000002",
            "S-1/A",
            "2024-03-15",
        )

        clean_db.mark_superseded_filings()

        assert _is_in_scope(clean_db, original) is False
        assert _is_in_scope(clean_db, amendment) is True


class TestTenKSupersession:
    def test_10ka_demotes_same_year_10k_only(self, clean_db: DatabaseAdapter) -> None:
        """A 10-K/A amending FY2022 demotes the FY2022 10-K but leaves the
        FY2023 10-K in scope."""
        company_id = create_test_company(clean_db, cik="0000000222", company_name="K10 Co")

        fy2022_original = _upsert(
            clean_db,
            company_id,
            "0000000222",
            "0000000222-23-000001",
            "10-K",
            "2023-02-15",
            period_end_date="2022-12-31",
        )
        fy2023_original = _upsert(
            clean_db,
            company_id,
            "0000000222",
            "0000000222-24-000001",
            "10-K",
            "2024-02-15",
            period_end_date="2023-12-31",
        )
        fy2022_amendment = _upsert(
            clean_db,
            company_id,
            "0000000222",
            "0000000222-24-000002",
            "10-K/A",
            "2024-06-01",
            period_end_date="2022-12-31",
        )

        clean_db.mark_superseded_filings()

        assert _is_in_scope(clean_db, fy2022_original) is False
        assert _is_in_scope(clean_db, fy2022_amendment) is True
        assert _is_in_scope(clean_db, fy2023_original) is True

    def test_null_period_end_date_is_skipped(self, clean_db: DatabaseAdapter) -> None:
        """A 10-K with NULL period_end_date is conservatively left in scope —
        no amendment can be safely paired without the fiscal-year key."""
        company_id = create_test_company(clean_db, cik="0000000333", company_name="Null Co")

        no_period = _upsert(
            clean_db,
            company_id,
            "0000000333",
            "0000000333-23-000001",
            "10-K",
            "2023-02-15",
            period_end_date=None,
        )
        later_no_period = _upsert(
            clean_db,
            company_id,
            "0000000333",
            "0000000333-24-000001",
            "10-K",
            "2024-02-15",
            period_end_date=None,
        )

        clean_db.mark_superseded_filings()

        assert _is_in_scope(clean_db, no_period) is True
        assert _is_in_scope(clean_db, later_no_period) is True
