"""Integration tests for scripts/backfill_legacy_reviewer_aliases.py.

Tests exercise:
  - Preview returns expected per-table counts.
  - Apply twice yields identical final state (idempotency proof).
  - Unmapped reviewer_id values are untouched.
  - Audit-log row is written for each invocation.

Fixture rows are inserted directly; the V2 pipeline is not involved.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
BACKFILL_SCRIPT = PROJECT_ROOT / "scripts" / "backfill_legacy_reviewer_aliases.py"


# ---------------------------------------------------------------------------
# Script loader
# ---------------------------------------------------------------------------


def _load_module(script_path: Path, mod_name: str) -> Any:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def backfill_cli() -> Any:
    return _load_module(BACKFILL_SCRIPT, "backfill_legacy_reviewer_aliases_integration")


# ---------------------------------------------------------------------------
# Shared DB cleanup fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def backfill_db(test_db_adapter):
    """Test DB adapter with auth + review tables cleaned before/after each test.

    We truncate review/ingest tables (to avoid FK conflicts from prior tests)
    and also truncate auth tables so each test starts with known alias state.
    """

    def _truncate(adapter) -> None:
        with adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET CONSTRAINTS ALL DEFERRED")
                # Remove decision/ingest data first (FK dependents).
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        DELETE FROM v2_review_decisions;
                        DELETE FROM v2_image_metric_confirmations;
                        DELETE FROM v2_ingest_batches;
                    EXCEPTION WHEN undefined_table THEN
                        NULL;
                    END $$;
                    """
                )
                # Auth tables.
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        TRUNCATE TABLE admin_audit_log CASCADE;
                        TRUNCATE TABLE auth_legacy_aliases CASCADE;
                        TRUNCATE TABLE auth_access_entries CASCADE;
                        TRUNCATE TABLE auth_sessions CASCADE;
                        TRUNCATE TABLE auth_users CASCADE;
                    EXCEPTION WHEN undefined_table THEN
                        NULL;
                    END $$;
                    """
                )
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

    _truncate(test_db_adapter)
    yield test_db_adapter
    _truncate(test_db_adapter)


# ---------------------------------------------------------------------------
# Fixture setup helpers
# ---------------------------------------------------------------------------


def _seed_user(db, email: str, role: str = "reviewer") -> str:
    """Insert an auth_users row; return its UUID id (as text)."""
    rows = db.query(
        """
        INSERT INTO auth_users (normalized_email, role, display_name)
        VALUES (%(email)s, %(role)s, %(display_name)s)
        ON CONFLICT (normalized_email) DO UPDATE SET role = EXCLUDED.role
        RETURNING id::text
        """,
        {"email": email, "role": role, "display_name": email.split("@")[0]},
    )
    return rows[0]["id"]


def _seed_alias(db, legacy_string: str, target_email: str, *, active: bool = True) -> None:
    """Insert an auth_legacy_aliases row."""
    db.execute(
        """
        INSERT INTO auth_legacy_aliases (legacy_reviewer_string, target_email, active)
        VALUES (%(legacy)s, %(email)s, %(active)s)
        ON CONFLICT (legacy_reviewer_string) DO UPDATE
            SET target_email = EXCLUDED.target_email,
                active = EXCLUDED.active
        """,
        {"legacy": legacy_string, "email": target_email, "active": active},
    )


def _insert_review_decision(db, reviewer_id: str, fact_id: str) -> None:
    """Insert a v2_review_decisions row with user_id=NULL."""
    db.execute(
        """
        INSERT INTO v2_review_decisions
            (fact_id, decision, reviewer_id, reviewer_notes)
        VALUES
            (%(fact_id)s::uuid, 'accept', %(reviewer_id)s, NULL)
        ON CONFLICT (fact_id) DO NOTHING
        """,
        {"fact_id": fact_id, "reviewer_id": reviewer_id},
    )


def _insert_ingest_batch(db, reviewer_id: str) -> str:
    """Insert a v2_ingest_batches row with user_id=NULL; return batch_id."""
    rows = db.query(
        """
        INSERT INTO v2_ingest_batches
            (kind, reviewer_id, criteria, resolved_query, limits, status)
        VALUES
            ('onboard', %(reviewer_id)s, '{}', '{}', '{}', 'complete')
        RETURNING batch_id::text
        """,
        {"reviewer_id": reviewer_id},
    )
    return rows[0]["batch_id"]


def _create_filing(db) -> int:
    """Create a minimal company+filing for FK purposes; return filing_id."""
    company_id = db.upsert_company(cik="0001234999", company_name="Backfill Test Corp")
    return db.upsert_filing(
        company_id=company_id,
        cik="0001234999",
        accession_number="0001234999-26-000001",
        form_type="S-1",
        filing_date="2026-01-01",
        sec_html_url="https://www.sec.gov/test/backfill",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )


def _create_image_asset(db, filing_id: int) -> str:
    """Create a minimal v2_image_assets row; return img_id as text.

    Unique-per-call filename so multiple tests sharing the same filing_id
    (via the idempotent upsert_filing) don't trip the
    (filing_id, filename) unique constraint.
    """
    import uuid

    filename = f"chart_{uuid.uuid4().hex[:8]}.png"
    rows = db.query(
        """
        INSERT INTO v2_image_assets
            (filing_id, filename, dom_locator, classification)
        VALUES
            (%(filing_id)s, %(filename)s, '#chart-1', 'chart')
        RETURNING img_id::text
        """,
        {"filing_id": filing_id, "filename": filename},
    )
    return rows[0]["img_id"]


def _insert_image_confirmation(db, img_id: str, reviewer_id: str) -> None:
    """Insert a v2_image_metric_confirmations row with user_id=NULL."""
    db.execute(
        """
        INSERT INTO v2_image_metric_confirmations
            (img_id, detected_metric_id, confirmed_metric_id, decision, reviewer_id)
        VALUES
            (%(img_id)s::uuid, 'cm_customers_period_end',
             'cm_customers_period_end', 'accept', %(reviewer_id)s)
        ON CONFLICT (img_id, reviewer_id,
            COALESCE(detected_metric_id, confirmed_metric_id, '')) DO NOTHING
        """,
        {"img_id": img_id, "reviewer_id": reviewer_id},
    )


def _get_fact_id(db, filing_id: int) -> str:
    """Create a v2_metric_facts row and return its fact_id (idempotent)."""
    import json

    # Use INSERT ... ON CONFLICT DO NOTHING, then SELECT to handle the case
    # where a prior test already inserted the same fact (same filing_id, metric,
    # period, etc.).  The unique index idx_v2_metric_facts_identity_unique
    # deduplicates on (filing_id, canonical_metric_id, period_start, period_end,
    # unit, scope, cohort_def, customer_type, source_type).
    db.execute(
        """
        INSERT INTO v2_metric_facts (
            filing_id, canonical_metric_id, value, value_raw, unit,
            period_type, period_start, period_end, source_type,
            source_locator, evidence_pack, confidence,
            extraction_method, requires_review, review_status
        ) VALUES (
            %(filing_id)s, 'cm_customers_period_end', 5000, '5,000', 'count',
            'point_in_time', '2026-01-01', '2026-12-31', 'html_table',
            %(locator)s, %(evidence)s, 0.9,
            'exact_match', TRUE, 'pending_review'
        )
        ON CONFLICT DO NOTHING
        """,
        {
            "filing_id": filing_id,
            "locator": json.dumps({"dom_locator": "#table1"}),
            "evidence": json.dumps({"snippet_html": "<td>5,000</td>"}),
        },
    )
    rows = db.query(
        """
        SELECT fact_id::text
        FROM v2_metric_facts
        WHERE filing_id = %(filing_id)s
          AND canonical_metric_id = 'cm_customers_period_end'
          AND period_start = '2026-01-01'
          AND period_end   = '2026-12-31'
          AND source_type  = 'html_table'
        LIMIT 1
        """,
        {"filing_id": filing_id},
    )
    return rows[0]["fact_id"]


def _count_with_user_id(db, table: str) -> int:
    rows = db.query(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id IS NOT NULL")
    return int(rows[0]["n"])


def _count_without_user_id(db, table: str) -> int:
    rows = db.query(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id IS NULL")
    return int(rows[0]["n"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBackfillPreview:
    def test_preview_returns_expected_counts(self, backfill_db, backfill_cli, monkeypatch):
        """Preview reports correct per-table row counts for mappable rows."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)

        # Seed auth infrastructure.
        _seed_user(db, "rgmarkey@gmail.com", "admin")
        _seed_alias(db, "RGM", "rgmarkey@gmail.com")

        # Create filing + supporting data.
        filing_id = _create_filing(db)
        fact_id = _get_fact_id(db, filing_id)
        img_id = _create_image_asset(db, filing_id)

        # Insert rows with reviewer_id='RGM' (mapped) and user_id=NULL.
        _insert_review_decision(db, "RGM", fact_id)
        _insert_ingest_batch(db, "RGM")
        _insert_image_confirmation(db, img_id, "RGM")

        monkeypatch.setattr("sys.argv", ["backfill_legacy_reviewer_aliases.py", "--preview"])
        rc = backfill_cli.main()

        assert rc == 0

        counts = backfill_cli.preview(db)
        assert counts["v2_review_decisions"] == 1
        assert counts["v2_image_metric_confirmations"] == 1
        assert counts["v2_ingest_batches"] == 1

    def test_preview_writes_audit_log(self, backfill_db, backfill_cli, monkeypatch):
        """--preview invocation writes an audit log row with dry_run=True."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)
        monkeypatch.setattr("sys.argv", ["backfill_legacy_reviewer_aliases.py", "--preview"])

        rc = backfill_cli.main()
        assert rc == 0

        rows = db.query(
            "SELECT action_type, before_state FROM admin_audit_log "
            "WHERE action_type = 'auth.backfill_legacy_aliases'"
        )
        assert len(rows) == 1
        assert rows[0]["action_type"] == "auth.backfill_legacy_aliases"
        # before_state contains dry_run=True JSON.
        before = rows[0]["before_state"]
        assert before is not None
        assert before["dry_run"] is True


class TestBackfillApply:
    def _setup_fixtures(self, db) -> dict:
        """Seed auth rows + review/ingest fixture rows; return counts dict."""
        _seed_user(db, "rgmarkey@gmail.com", "admin")
        _seed_user(db, "mayujoiner@gmail.com", "reviewer")
        _seed_alias(db, "RGM", "rgmarkey@gmail.com")
        _seed_alias(db, "Mayu", "mayujoiner@gmail.com")

        filing_id = _create_filing(db)
        fact_id = _get_fact_id(db, filing_id)
        img_id = _create_image_asset(db, filing_id)

        _insert_review_decision(db, "RGM", fact_id)
        _insert_ingest_batch(db, "Mayu")
        _insert_image_confirmation(db, img_id, "RGM")

        return {"filing_id": filing_id, "fact_id": fact_id, "img_id": img_id}

    def test_apply_updates_all_tables(self, backfill_db, backfill_cli, monkeypatch):
        """--apply --confirm sets user_id on mapped rows in all three tables."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)
        self._setup_fixtures(db)

        # Confirm all start with user_id=NULL.
        assert _count_without_user_id(db, "v2_review_decisions") == 1
        assert _count_without_user_id(db, "v2_image_metric_confirmations") == 1
        assert _count_without_user_id(db, "v2_ingest_batches") == 1

        monkeypatch.setattr(
            "sys.argv",
            ["backfill_legacy_reviewer_aliases.py", "--apply", "--confirm"],
        )
        rc = backfill_cli.main()
        assert rc == 0

        # All mapped rows should now have user_id set.
        assert _count_with_user_id(db, "v2_review_decisions") == 1
        assert _count_with_user_id(db, "v2_image_metric_confirmations") == 1
        assert _count_with_user_id(db, "v2_ingest_batches") == 1

    def test_apply_twice_is_idempotent(self, backfill_db, backfill_cli, monkeypatch):
        """Running --apply --confirm twice yields the same final state (idempotency proof)."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)
        self._setup_fixtures(db)

        monkeypatch.setattr(
            "sys.argv",
            ["backfill_legacy_reviewer_aliases.py", "--apply", "--confirm"],
        )

        # First apply.
        rc1 = backfill_cli.main()
        assert rc1 == 0

        state_after_first = {
            "decisions_with_user_id": _count_with_user_id(db, "v2_review_decisions"),
            "confirmations_with_user_id": _count_with_user_id(db, "v2_image_metric_confirmations"),
            "batches_with_user_id": _count_with_user_id(db, "v2_ingest_batches"),
        }

        # Second apply (should be a no-op for user_id updates).
        after_second = backfill_cli.apply(db)
        assert after_second["v2_review_decisions"] == 0
        assert after_second["v2_image_metric_confirmations"] == 0
        assert after_second["v2_ingest_batches"] == 0

        # Final state is unchanged.
        assert (
            _count_with_user_id(db, "v2_review_decisions")
            == state_after_first["decisions_with_user_id"]
        )
        assert (
            _count_with_user_id(db, "v2_image_metric_confirmations")
            == state_after_first["confirmations_with_user_id"]
        )
        assert (
            _count_with_user_id(db, "v2_ingest_batches")
            == state_after_first["batches_with_user_id"]
        )

    def test_unmapped_reviewer_id_untouched(self, backfill_db, backfill_cli, monkeypatch):
        """Rows with reviewer_id that has no active alias are left with user_id=NULL."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)

        # Seed one user + alias for RGM only.
        _seed_user(db, "rgmarkey@gmail.com", "admin")
        _seed_alias(db, "RGM", "rgmarkey@gmail.com")

        filing_id = _create_filing(db)
        fact_id_rgm = _get_fact_id(db, filing_id)

        # Mapped row (RGM).
        _insert_review_decision(db, "RGM", fact_id_rgm)

        # Unmapped batch (reviewer_id='UnknownReviewer' — no alias exists).
        _insert_ingest_batch(db, "UnknownReviewer")

        monkeypatch.setattr(
            "sys.argv",
            ["backfill_legacy_reviewer_aliases.py", "--apply", "--confirm"],
        )
        rc = backfill_cli.main()
        assert rc == 0

        # RGM decision should be mapped.
        assert _count_with_user_id(db, "v2_review_decisions") == 1

        # UnknownReviewer batch should remain unmapped.
        unmapped_batches = db.query(
            "SELECT user_id FROM v2_ingest_batches WHERE reviewer_id = 'UnknownReviewer'"
        )
        assert len(unmapped_batches) == 1
        assert unmapped_batches[0]["user_id"] is None

    def test_apply_writes_audit_log(self, backfill_db, backfill_cli, monkeypatch):
        """--apply --confirm writes one audit log row with before/after counts."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)
        self._setup_fixtures(db)

        monkeypatch.setattr(
            "sys.argv",
            ["backfill_legacy_reviewer_aliases.py", "--apply", "--confirm"],
        )
        rc = backfill_cli.main()
        assert rc == 0

        rows = db.query(
            "SELECT action_type, before_state, after_state "
            "FROM admin_audit_log "
            "WHERE action_type = 'auth.backfill_legacy_aliases'"
        )
        # --apply writes 1 audit row from the call inside apply path
        # (preview within apply does NOT write its own audit row — only main() writes it).
        assert len(rows) >= 1
        last = rows[-1]
        assert last["action_type"] == "auth.backfill_legacy_aliases"
        assert last["before_state"] is not None
        assert last["after_state"] is not None
        assert last["after_state"]["dry_run"] is False

    def test_apply_without_confirm_returns_error(self, backfill_db, backfill_cli, monkeypatch):
        """--apply without --confirm returns non-zero exit code."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)
        monkeypatch.setattr("sys.argv", ["backfill_legacy_reviewer_aliases.py", "--apply"])
        rc = backfill_cli.main()
        assert rc != 0

    def test_inactive_alias_does_not_backfill(self, backfill_db, backfill_cli, monkeypatch):
        """Rows whose reviewer_id matches an inactive alias are NOT updated."""
        db = backfill_db
        monkeypatch.setenv("DATABASE_URL", db.connection_string)

        _seed_user(db, "rgmarkey@gmail.com", "admin")
        # Insert an INACTIVE alias for RGM.
        _seed_alias(db, "RGM", "rgmarkey@gmail.com", active=False)

        filing_id = _create_filing(db)
        fact_id = _get_fact_id(db, filing_id)
        _insert_review_decision(db, "RGM", fact_id)

        monkeypatch.setattr(
            "sys.argv",
            ["backfill_legacy_reviewer_aliases.py", "--apply", "--confirm"],
        )
        rc = backfill_cli.main()
        assert rc == 0

        # Should NOT have been backfilled because alias is inactive.
        assert _count_with_user_id(db, "v2_review_decisions") == 0
