"""Integration coverage for accession_number normalization.

Two halves:

1. ``upsert_filing`` canonicalizes incoming accession strings before the
   SQL runs and rejects values with no embedded SEC token. Prevents the
   class of bug where a full EDGAR path got persisted verbatim.

2. The one-shot backfill migration (``sql/41_normalize_accession_numbers.sql``)
   fixes any rows already stored with malformed values while leaving
   synthetic-namespace rows untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infra.validation import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION_SQL = (_REPO_ROOT / "sql" / "41_normalize_accession_numbers.sql").read_text()


def _seed_company(db, cik: str = "0001633917", name: str = "PayPal Holdings Inc"):
    return db.upsert_company(cik=cik, company_name=name)


@pytest.mark.integration
class TestUpsertFilingNormalizes:
    def test_path_prefixed_accession_stored_as_bare_token(self, clean_db):
        """Regression: the PayPal-8K shape that tripped the path-traversal guard."""
        company_id = _seed_company(clean_db)
        filing_id = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001633917",
            accession_number="edgar/data/1633917/0001633917-23-000220.txt",
            form_type="8-K",
            filing_date="2023-11-01",
            sec_html_url="https://example.com/f.htm",
        )
        rows = clean_db.query(
            "SELECT accession_number FROM filings WHERE filing_id = %(fid)s",
            {"fid": filing_id},
        )
        assert rows[0]["accession_number"] == "0001633917-23-000220"

    def test_bare_token_unchanged(self, clean_db):
        company_id = _seed_company(clean_db)
        clean_db.upsert_filing(
            company_id=company_id,
            cik="0001633917",
            accession_number="0001633917-23-000220",
            form_type="8-K",
            filing_date="2023-11-01",
            sec_html_url="https://example.com/f.htm",
        )
        rows = clean_db.query("SELECT accession_number FROM filings WHERE cik = '0001633917'")
        assert rows[0]["accession_number"] == "0001633917-23-000220"

    def test_unparseable_accession_raises(self, clean_db):
        """No SEC-shaped token anywhere → fail at write, don't persist junk."""
        company_id = _seed_company(clean_db)
        with pytest.raises(ValidationError, match="no SEC-shaped token"):
            clean_db.upsert_filing(
                company_id=company_id,
                cik="0001633917",
                accession_number="definitely-not-an-accession",
                form_type="8-K",
                filing_date="2023-11-01",
                sec_html_url="https://example.com/f.htm",
            )


@pytest.mark.integration
class TestBackfillMigration:
    def test_backfill_normalizes_malformed_rows(self, clean_db):
        """Run the one-shot migration; malformed rows collapse to the bare token."""
        company_id = _seed_company(clean_db)

        # Bypass upsert_filing's normalizer to plant malformed rows directly.
        # This mirrors the prod state we want the backfill to fix.
        with clean_db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO filings (company_id, cik, accession_number, form_type,
                                         filing_date, sec_html_url, updated_at)
                    VALUES
                      (%(cid)s, %(cik)s, 'edgar/data/1633917/0001633917-23-000220.txt',
                       '8-K', '2023-11-01', 'https://x/f1.htm', now()),
                      (%(cid)s, %(cik)s, 'edgar/data/1633917/0001633917-23-000444.txt',
                       '8-K', '2023-05-01', 'https://x/f2.htm', now())
                    """,
                    {"cid": company_id, "cik": "0001633917"},
                )

        # Apply the backfill migration SQL directly.
        with clean_db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(_MIGRATION_SQL)

        rows = clean_db.query(
            "SELECT accession_number FROM filings WHERE company_id = %(cid)s ORDER BY filing_date",
            {"cid": company_id},
        )
        assert {r["accession_number"] for r in rows} == {
            "0001633917-23-000220",
            "0001633917-23-000444",
        }

    def test_backfill_leaves_valid_rows_untouched(self, clean_db):
        company_id = _seed_company(clean_db)
        clean_db.upsert_filing(
            company_id=company_id,
            cik="0001633917",
            accession_number="0001633917-23-000220",
            form_type="8-K",
            filing_date="2023-11-01",
            sec_html_url="https://x/f.htm",
        )

        with clean_db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(_MIGRATION_SQL)

        rows = clean_db.query(
            "SELECT accession_number FROM filings WHERE company_id = %(cid)s",
            {"cid": company_id},
        )
        assert rows[0]["accession_number"] == "0001633917-23-000220"

    def test_backfill_leaves_synthetic_namespaces_untouched(self, clean_db):
        """presentation:* and transcript:* rows must not be touched by the backfill."""
        company_id = _seed_company(clean_db, cik="0001000001", name="Synthetic Co")

        with clean_db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO filings (company_id, cik, accession_number, form_type,
                                         filing_date, sec_html_url, updated_at)
                    VALUES
                      (%(cid)s, %(cik)s,
                       'presentation:0001000001/0001000001-23-000001/deck.pdf',
                       'investor_presentation', '2023-06-01', NULL, now()),
                      (%(cid)s, %(cik)s, 'transcript:SYN:2023-06-01:Q2',
                       'earnings_transcript', '2023-06-01', NULL, now())
                    """,
                    {"cid": company_id, "cik": "0001000001"},
                )

        with clean_db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(_MIGRATION_SQL)

        rows = clean_db.query(
            "SELECT accession_number FROM filings WHERE company_id = %(cid)s "
            "ORDER BY accession_number",
            {"cid": company_id},
        )
        assert [r["accession_number"] for r in rows] == [
            "presentation:0001000001/0001000001-23-000001/deck.pdf",
            "transcript:SYN:2023-06-01:Q2",
        ]
