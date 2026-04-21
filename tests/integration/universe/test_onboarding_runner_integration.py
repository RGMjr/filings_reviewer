"""Integration tests for src/universe/onboarding_runner.py.

Requires TEST_DATABASE_URL pointing at a live PostgreSQL instance (Docker
Compose on port 5433 by default).  The session-scoped `_apply_migrations_to_test_db`
fixture in tests/integration/conftest.py ensures sql/39_v2_ingest_batches.sql
has been applied before these tests run.

All tests use `clean_db` (function-scoped) which TRUNCATEs relevant tables
and `clean_batch_db` (local) which additionally truncates v2_ingest_batch_filings
and v2_ingest_batches.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from src.infra.db import DatabaseAdapter
from src.universe.onboarding import Candidate, FilingEvent, RunSummary
from src.universe.onboarding_runner import (
    claim_batch,
    run_one,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CRITERIA = {"year": "2024", "form_types": ["s1f1"], "sic_codes": ["7372"]}
_RESOLVED_QUERY = {"sic_codes": ["7372"], "form_types": ["S-1"], "year_min": 2024, "year_max": 2024}
_LIMITS = {"volume_band": "ok", "total": 2}


def _insert_batch(
    db: DatabaseAdapter,
    *,
    status: str = "queued",
    kind: str = "onboard",
    reviewer_id: str = "test_runner",
    total_filings: int = 2,
) -> str:
    """Insert a v2_ingest_batches row and return batch_id (str)."""
    rows = db.query(
        """
        INSERT INTO v2_ingest_batches
            (kind, reviewer_id, criteria, resolved_query, limits, total_filings, status)
        VALUES
            (%(kind)s, %(reviewer_id)s, %(criteria)s, %(resolved_query)s, %(limits)s,
             %(total_filings)s, %(status)s)
        RETURNING batch_id::text
        """,
        {
            "kind": kind,
            "reviewer_id": reviewer_id,
            "criteria": json.dumps(_CRITERIA),
            "resolved_query": json.dumps(_RESOLVED_QUERY),
            "limits": json.dumps(_LIMITS),
            "total_filings": total_filings,
            "status": status,
        },
    )
    return rows[0]["batch_id"]


def _insert_batch_filing(
    db: DatabaseAdapter,
    batch_id: str,
    filing_id: int,
    initial_bucket: str = "new",
    current_status: str = "queued",
) -> None:
    db.execute(
        """
        INSERT INTO v2_ingest_batch_filings
            (batch_id, filing_id, initial_bucket, current_status)
        VALUES (%s, %s, %s, %s)
        """,
        [batch_id, filing_id, initial_bucket, current_status],
    )


def _get_batch(db: DatabaseAdapter, batch_id: str) -> dict[str, Any] | None:
    rows = db.query("SELECT * FROM v2_ingest_batches WHERE batch_id = %s", [batch_id])
    return dict(rows[0]) if rows else None


def _get_batch_filing(db: DatabaseAdapter, batch_id: str, filing_id: int) -> dict[str, Any] | None:
    rows = db.query(
        "SELECT * FROM v2_ingest_batch_filings WHERE batch_id = %s AND filing_id = %s",
        [batch_id, filing_id],
    )
    return dict(rows[0]) if rows else None


def _truncate_batch_tables(db: DatabaseAdapter) -> None:
    """Truncate batch tables without touching filings/companies (clean_db handles those)."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DO $$
                BEGIN
                    TRUNCATE TABLE v2_ingest_batch_filings CASCADE;
                    TRUNCATE TABLE v2_ingest_batches CASCADE;
                EXCEPTION WHEN undefined_table THEN NULL;
                END $$;
                """
            )


@pytest.fixture
def clean_batch_db(clean_db: DatabaseAdapter) -> DatabaseAdapter:
    """Extend clean_db to also truncate batch tables before each test."""
    _truncate_batch_tables(clean_db)
    yield clean_db
    _truncate_batch_tables(clean_db)


def _make_candidate(filing_id: int, already_extracted: bool = False) -> Candidate:
    return Candidate(
        filing_id=filing_id,
        cik="0001234567",
        ticker="TEST",
        company_name="Test Corp",
        form_type="S-1",
        filing_date="2024-01-15",
        industry_code="7372",
        accession_number=f"0001234567-24-{filing_id:06d}",
        primary_doc_url=f"https://www.sec.gov/test/{filing_id}",
        txt_url=None,
        already_extracted=already_extracted,
        extracted_at=None,
    )


# ---------------------------------------------------------------------------
# Happy path: 2 filings, mocked onboard() emits events
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_two_filings_complete(self, clean_batch_db: DatabaseAdapter) -> None:
        db = clean_batch_db

        # Create company + 2 filings in DB (required by FK).
        from tests.integration.conftest import create_test_company_and_filing

        _, fid1 = create_test_company_and_filing(
            db, cik="0001111111", accession_number="0001111111-24-000001"
        )
        _, fid2 = create_test_company_and_filing(
            db,
            cik="0001111112",
            accession_number="0001111112-24-000002",
            company_name="Test Corp 2",
        )

        batch_id = _insert_batch(db, total_filings=2)
        _insert_batch_filing(db, batch_id, fid1, "new")
        _insert_batch_filing(db, batch_id, fid2, "new")

        batch_row = claim_batch(db, uuid.UUID(batch_id))
        assert batch_row is not None

        candidates = [_make_candidate(fid1), _make_candidate(fid2)]

        # Mock onboard() to emit events and NOT touch SEC/filesystem.
        def _fake_onboard(db_, cands, reextract, *, progress_cb=None, abort_check=None, **kw):
            for c in cands:
                if progress_cb:
                    progress_cb(FilingEvent(filing_id=c.filing_id, status="started"))
                    progress_cb(
                        FilingEvent(
                            filing_id=c.filing_id,
                            status="succeeded",
                            message="3 facts persisted (force=False)",
                        )
                    )
            return RunSummary(succeeded=2, failed=0, skipped_reviewed=0)

        with patch("src.universe.onboarding_runner.onboard", side_effect=_fake_onboard):
            with patch(
                "src.universe.onboarding_runner.load_candidates_by_filing_ids",
                return_value=candidates,
            ):
                run_one(db, batch_row)

        # Verify batch is complete.
        batch = _get_batch(db, batch_id)
        assert batch is not None
        assert batch["status"] == "complete"
        assert batch["finished_at"] is not None

        # Verify both filings persisted.
        bf1 = _get_batch_filing(db, batch_id, fid1)
        bf2 = _get_batch_filing(db, batch_id, fid2)
        assert bf1 is not None and bf1["current_status"] == "persisted"
        assert bf1["fact_count"] == 3
        assert bf2 is not None and bf2["current_status"] == "persisted"
        assert bf2["fact_count"] == 3


# ---------------------------------------------------------------------------
# Cancellation: flip batch status mid-run, assert remaining filings cancelled
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_cancelled_batch_flips_queued_filings(self, clean_batch_db: DatabaseAdapter) -> None:
        db = clean_batch_db

        from tests.integration.conftest import create_test_company_and_filing

        _, fid1 = create_test_company_and_filing(
            db, cik="0002111111", accession_number="0002111111-24-000001"
        )
        _, fid2 = create_test_company_and_filing(
            db,
            cik="0002111112",
            accession_number="0002111112-24-000002",
            company_name="Cancel Corp 2",
        )

        batch_id = _insert_batch(db, total_filings=2)
        _insert_batch_filing(db, batch_id, fid1, "new")
        _insert_batch_filing(db, batch_id, fid2, "new")

        batch_row = claim_batch(db, uuid.UUID(batch_id))
        assert batch_row is not None

        candidates = [_make_candidate(fid1), _make_candidate(fid2)]

        def _fake_onboard(db_, cands, reextract, *, progress_cb=None, abort_check=None, **kw):
            # Emit started for fid1, then check abort — fid2 will be left queued.
            if progress_cb:
                progress_cb(FilingEvent(filing_id=cands[0].filing_id, status="started"))
                progress_cb(
                    FilingEvent(
                        filing_id=cands[0].filing_id,
                        status="succeeded",
                        message="1 facts persisted (force=False)",
                    )
                )
            # Simulate abort_check firing before fid2 (abort_check is called by onboard internally,
            # but here we just return early without processing fid2, and abort_check returns True).
            return RunSummary(succeeded=1, failed=0, skipped_reviewed=0)

        # Flip batch status to 'cancelled' in DB so should_abort() returns True.
        db.execute(
            "UPDATE v2_ingest_batches SET status='cancelled', cancelled_at=NOW() WHERE batch_id=%s",
            [batch_id],
        )

        with patch("src.universe.onboarding_runner.onboard", side_effect=_fake_onboard):
            with patch(
                "src.universe.onboarding_runner.load_candidates_by_filing_ids",
                return_value=candidates,
            ):
                run_one(db, batch_row)

        # fid1 should be persisted (onboard ran it).
        bf1 = _get_batch_filing(db, batch_id, fid1)
        assert bf1 is not None and bf1["current_status"] == "persisted"

        # fid2 was left 'queued' by fake_onboard and should be flipped to 'cancelled'.
        bf2 = _get_batch_filing(db, batch_id, fid2)
        assert bf2 is not None and bf2["current_status"] == "cancelled"


# ---------------------------------------------------------------------------
# Concurrency: two claim_batch calls — only one wins
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_only_one_claimer_wins(self, clean_batch_db: DatabaseAdapter) -> None:
        db = clean_batch_db

        batch_id = _insert_batch(db, total_filings=1)
        bid = uuid.UUID(batch_id)

        # First claim should succeed.
        row1 = claim_batch(db, bid)
        assert row1 is not None

        # Second claim should fail (row already locked with run_lock_until in the future).
        row2 = claim_batch(db, bid)
        assert row2 is None


# ---------------------------------------------------------------------------
# Expired lock: backdate run_lock_until, verify claim_batch succeeds
# ---------------------------------------------------------------------------


class TestExpiredLock:
    def test_expired_lock_can_be_reclaimed(self, clean_batch_db: DatabaseAdapter) -> None:
        db = clean_batch_db

        batch_id = _insert_batch(db, status="running", total_filings=1)

        # Backdate run_lock_until to the past.
        db.execute(
            """
            UPDATE v2_ingest_batches
            SET run_lock_until = NOW() - INTERVAL '1 minute'
            WHERE batch_id = %s
            """,
            [batch_id],
        )

        row = claim_batch(db, uuid.UUID(batch_id))
        assert row is not None, "Should be able to reclaim a batch with an expired lock"

    def test_active_lock_blocks_claim(self, clean_batch_db: DatabaseAdapter) -> None:
        db = clean_batch_db

        batch_id = _insert_batch(db, status="running", total_filings=1)

        # Set run_lock_until to the future.
        db.execute(
            """
            UPDATE v2_ingest_batches
            SET run_lock_until = NOW() + INTERVAL '15 minutes'
            WHERE batch_id = %s
            """,
            [batch_id],
        )

        row = claim_batch(db, uuid.UUID(batch_id))
        assert row is None, "Should not be able to claim a batch with an active lock"
