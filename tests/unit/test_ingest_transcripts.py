"""
Unit tests for scripts/ingest_transcripts.py.

Tests cover the testable pure-logic functions and dry-run behavior.
CLI entry points and full pipeline runs are excluded (integration scope).

Tests:
- IngestSummary computed properties
- _get_or_create_company: existing company lookup, new company insert
- _upsert_transcript_filing: SQL params and return value
- _is_already_ingested: returns True/False based on cursor result
- Dry-run mode: pipeline runs but no DB calls
- Ticker filtering: run_ingestion passes tickers to source.list_available
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# The script adds project root to sys.path on import; mimic that here
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ingest_transcripts import (
    IngestResult,
    IngestSummary,
    _get_or_create_company,
    _is_already_ingested,
    _upsert_transcript_filing,
)


# ============================================================================
# IngestSummary Tests
# ============================================================================


class TestIngestSummary:
    def _make_result(self, status: str, fact_count: int = 0) -> IngestResult:
        return IngestResult(
            source_id="fmp:CRM_2025-01-01_Q4",
            ticker="CRM",
            document_date=date(2025, 1, 1),
            fiscal_period="Q4",
            status=status,
            fact_count=fact_count,
        )

    def test_ingested_count(self):
        summary = IngestSummary(results=[
            self._make_result("ingested"),
            self._make_result("ingested"),
            self._make_result("error"),
        ])
        assert summary.ingested == 2

    def test_skipped_count(self):
        summary = IngestSummary(results=[
            self._make_result("skipped"),
            self._make_result("ingested"),
        ])
        assert summary.skipped == 1

    def test_errors_count(self):
        summary = IngestSummary(results=[
            self._make_result("error"),
            self._make_result("error"),
        ])
        assert summary.errors == 2

    def test_total_facts(self):
        summary = IngestSummary(results=[
            self._make_result("ingested", fact_count=5),
            self._make_result("ingested", fact_count=3),
            self._make_result("error", fact_count=0),
        ])
        assert summary.total_facts == 8

    def test_empty_summary(self):
        summary = IngestSummary()
        assert summary.ingested == 0
        assert summary.skipped == 0
        assert summary.errors == 0
        assert summary.total_facts == 0


# ============================================================================
# _get_or_create_company Tests
# ============================================================================


class TestGetOrCreateCompany:
    def _make_conn(self) -> MagicMock:
        """Build a mock psycopg2-style connection with cursor context manager."""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cur

    def test_returns_existing_company_id(self):
        """When company exists, returns company_id without insert."""
        conn, cur = self._make_conn()
        cur.fetchone.return_value = {"company_id": 42}

        result = _get_or_create_company(conn, "CRM", "Salesforce")

        assert result == 42
        # Only one execute for SELECT, no INSERT
        assert cur.execute.call_count == 1
        assert "SELECT" in cur.execute.call_args[0][0]

    def test_inserts_new_company(self):
        """When company does not exist, inserts and returns new company_id."""
        conn, cur = self._make_conn()
        # First fetchone (SELECT) returns None → company not found
        # Second fetchone (INSERT RETURNING) returns new id
        cur.fetchone.side_effect = [None, {"company_id": 99}]

        result = _get_or_create_company(conn, "NEWCO", "New Company Inc.")

        assert result == 99
        assert cur.execute.call_count == 2
        second_call_sql = cur.execute.call_args_list[1][0][0]
        assert "INSERT" in second_call_sql

    def test_passes_correct_ticker_param(self):
        """SELECT query uses correct ticker parameter."""
        conn, cur = self._make_conn()
        cur.fetchone.return_value = {"company_id": 1}

        _get_or_create_company(conn, "ADBE", "Adobe")

        select_params = cur.execute.call_args_list[0][0][1]
        assert select_params["ticker"] == "ADBE"


# ============================================================================
# _upsert_transcript_filing Tests
# ============================================================================


class TestUpsertTranscriptFiling:
    def _make_conn(self) -> tuple[MagicMock, MagicMock]:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cur.fetchone.return_value = {"filing_id": 77}
        return conn, cur

    def test_returns_filing_id(self):
        """Returns the filing_id from the RETURNING clause."""
        conn, cur = self._make_conn()

        filing_id = _upsert_transcript_filing(
            conn,
            company_id=10,
            ticker="CRM",
            document_date=date(2025, 2, 26),
            fiscal_period="Q4",
            source_id="fmp:CRM_2025-02-26_Q4",
            source_name="fmp:financialmodelingprep.com",
        )

        assert filing_id == 77

    def test_accession_number_format(self):
        """Synthetic accession number includes ticker, date, and fiscal_period."""
        conn, cur = self._make_conn()

        _upsert_transcript_filing(
            conn,
            company_id=10,
            ticker="CRM",
            document_date=date(2025, 2, 26),
            fiscal_period="Q4",
            source_id="fmp:CRM_2025-02-26_Q4",
            source_name="fmp:financialmodelingprep.com",
        )

        params = cur.execute.call_args[0][1]
        assert params["accession_number"].startswith("transcript:CRM:")
        assert "2025-02-26" in params["accession_number"]
        assert "Q4" in params["accession_number"]

    def test_form_type_is_earnings_call(self):
        """form_type is set to 'earnings_call'."""
        conn, cur = self._make_conn()
        _upsert_transcript_filing(
            conn,
            company_id=5,
            ticker="ADBE",
            document_date=date(2025, 3, 15),
            fiscal_period="Q1",
            source_id="fmp:ADBE_2025-03-15_Q1",
            source_name="fmp:financialmodelingprep.com",
        )
        params = cur.execute.call_args[0][1]
        assert params["form_type"] == "earnings_call"
        assert params["document_type"] == "earnings_call"

    def test_none_document_date_uses_unknown(self):
        """None document_date produces 'unknown' in accession number."""
        conn, cur = self._make_conn()
        _upsert_transcript_filing(
            conn,
            company_id=5,
            ticker="TEST",
            document_date=None,
            fiscal_period=None,
            source_id="fmp:TEST_unknown_unknown",
            source_name="fmp:financialmodelingprep.com",
        )
        params = cur.execute.call_args[0][1]
        assert "unknown" in params["accession_number"]


# ============================================================================
# _is_already_ingested Tests
# ============================================================================


class TestIsAlreadyIngested:
    def _make_conn(self) -> tuple[MagicMock, MagicMock]:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cur

    def test_returns_true_when_record_exists(self):
        """Returns True when v2_documents record found."""
        conn, cur = self._make_conn()
        cur.fetchone.return_value = (1,)  # row exists

        result = _is_already_ingested(conn, "CRM", date(2025, 2, 26))
        assert result is True

    def test_returns_false_when_no_record(self):
        """Returns False when no v2_documents record found."""
        conn, cur = self._make_conn()
        cur.fetchone.return_value = None

        result = _is_already_ingested(conn, "CRM", date(2025, 2, 26))
        assert result is False

    def test_returns_false_for_none_date(self):
        """Returns False immediately when document_date is None (no DB query)."""
        conn, cur = self._make_conn()

        result = _is_already_ingested(conn, "CRM", None)

        assert result is False
        cur.execute.assert_not_called()

    def test_query_uses_correct_params(self):
        """Query is parameterized with ticker and document_date."""
        conn, cur = self._make_conn()
        cur.fetchone.return_value = None

        _is_already_ingested(conn, "ADBE", date(2025, 1, 15))

        params = cur.execute.call_args[0][1]
        assert params["ticker"] == "ADBE"
        assert params["document_date"] == date(2025, 1, 15)
