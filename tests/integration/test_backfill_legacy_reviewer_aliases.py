"""Integration tests for scripts/backfill_legacy_reviewer_aliases.py.

The primary assertion is that ``apply()`` actually persists ``user_id``
populations on the three target tables — i.e., that the UPDATEs land
durably in the database, not just within the script's transaction.

History: gh-604 reported in prod (2026-05-11) that ``apply()`` reported
success but its UPDATEs appeared to be rolled back. The fragment named
"missing ``conn.commit()``" as the cause; the framework
(``DatabaseAdapter.get_connection()``) does auto-commit on clean exit,
so the literal diagnosis is suspect. This test reproduces the
end-to-end behaviour an operator depends on: after ``apply()`` returns,
``user_id`` is set on a separate connection's view of the row.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "backfill_legacy_reviewer_aliases.py"


def _load_script() -> ModuleType:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "backfill_legacy_reviewer_aliases_integration"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load_script()


# ---------------------------------------------------------------------------
# Seeding / cleanup
# ---------------------------------------------------------------------------

_LEGACY_REVIEWER = "legacy_reviewer_604"
_TARGET_EMAIL = "alias-target-604@example.com"
_OTHER_REVIEWER = "unmapped_reviewer_604"


@pytest.fixture()
def seeded(clean_db):
    """Seed auth_users + auth_legacy_aliases + one row per target table.

    Returns the (db, user_id, filing_id, fact_id, img_id, batch_id) tuple.
    Cleans up auth/admin tables (which clean_db does not touch) on exit.
    """
    db = clean_db

    # Clean auth-side state that clean_db doesn't manage.
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM v2_image_metric_confirmations")
            cur.execute("DELETE FROM v2_ingest_batches")
            cur.execute("DELETE FROM admin_audit_log")
            cur.execute("DELETE FROM auth_legacy_aliases")
            cur.execute("DELETE FROM auth_sessions")
            cur.execute("DELETE FROM auth_users")

    # auth_users + auth_legacy_aliases.
    user_rows = db.query(
        """
        INSERT INTO auth_users (google_sub, normalized_email, display_name, role)
        VALUES (NULL, %s, 'Alias Target', 'reviewer')
        RETURNING id::text
        """,
        (_TARGET_EMAIL,),
    )
    user_id = user_rows[0]["id"]

    db.execute(
        """
        INSERT INTO auth_legacy_aliases (legacy_reviewer_string, target_email, active)
        VALUES (%s, %s, TRUE)
        """,
        (_LEGACY_REVIEWER, _TARGET_EMAIL),
    )

    # Filing + fact for v2_review_decisions.
    company_id = db.upsert_company(
        cik="0006040001",
        company_name="GH604 Test Co",
        ticker=None,
        industry_code=None,
    )
    filing_id = db.upsert_filing(
        company_id=company_id,
        cik="0006040001",
        accession_number="0006040001-99-000001",
        form_type="S-1",
        filing_date="2024-01-15",
        sec_html_url="https://www.sec.gov/test/0006040001",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )

    fact_rows = db.query(
        """
        INSERT INTO v2_metric_facts (
            filing_id, canonical_metric_id, value, value_raw, unit,
            period_type, source_type, source_locator, evidence_pack,
            confidence, extraction_method, requires_review, review_status
        ) VALUES (
            %(filing_id)s, 'cm_customers_period_end', 100, '100', 'count',
            'point_in_time', 'html_table', '{}'::jsonb, '{}'::jsonb,
            0.9, 'exact_match', TRUE, 'pending_review'
        )
        RETURNING fact_id::text
        """,
        {"filing_id": filing_id},
    )
    fact_id = fact_rows[0]["fact_id"]

    # v2_review_decisions row mapped to legacy reviewer (and one unmapped row).
    db.execute(
        """
        INSERT INTO v2_review_decisions (fact_id, decision, reviewer_id)
        VALUES (%(fact_id)s, 'accept', %(rev)s)
        """,
        {"fact_id": fact_id, "rev": _LEGACY_REVIEWER},
    )

    # v2_image_metric_confirmations row (needs an image first).
    img_rows = db.query(
        """
        INSERT INTO v2_image_assets
            (filing_id, filename, file_path, dom_locator, classification)
        VALUES
            (%(filing_id)s, 'gh604.png', 'pipeline/test/gh604.png',
             '/html/body/img[1]', 'chart')
        RETURNING img_id::text
        """,
        {"filing_id": filing_id},
    )
    img_id = img_rows[0]["img_id"]

    db.execute(
        """
        INSERT INTO v2_image_metric_confirmations
            (img_id, reviewer_id, decision, rejection_reason)
        VALUES (%(img_id)s, %(rev)s, 'reject', 'no_relevant_metrics')
        """,
        {"img_id": img_id, "rev": _LEGACY_REVIEWER},
    )

    # v2_ingest_batches row.
    batch_rows = db.query(
        """
        INSERT INTO v2_ingest_batches
            (kind, reviewer_id, criteria, resolved_query, limits, status)
        VALUES ('onboard', %(rev)s, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'complete')
        RETURNING batch_id::text
        """,
        {"rev": _LEGACY_REVIEWER},
    )
    batch_id = batch_rows[0]["batch_id"]

    # Unmapped row on v2_review_decisions (different reviewer string with no alias).
    # Distinct period_end to avoid unique-identity collision with fact 1.
    fact2_rows = db.query(
        """
        INSERT INTO v2_metric_facts (
            filing_id, canonical_metric_id, value, value_raw, unit,
            period_type, period_start, period_end,
            source_type, source_locator, evidence_pack,
            confidence, extraction_method, requires_review, review_status
        ) VALUES (
            %(filing_id)s, 'cm_customers_period_end', 200, '200', 'count',
            'point_in_time', '2022-01-01', '2022-12-31',
            'html_table', '{}'::jsonb, '{}'::jsonb,
            0.9, 'exact_match', TRUE, 'pending_review'
        )
        RETURNING fact_id::text
        """,
        {"filing_id": filing_id},
    )
    fact2_id = fact2_rows[0]["fact_id"]
    db.execute(
        """
        INSERT INTO v2_review_decisions (fact_id, decision, reviewer_id)
        VALUES (%(fact_id)s, 'accept', %(rev)s)
        """,
        {"fact_id": fact2_id, "rev": _OTHER_REVIEWER},
    )

    yield {
        "db": db,
        "user_id": user_id,
        "filing_id": filing_id,
        "fact_id": fact_id,
        "fact2_id": fact2_id,
        "img_id": img_id,
        "batch_id": batch_id,
    }

    # Teardown: scrub state we created. NULL user_id FKs first so the auth_users
    # delete doesn't trip the FK constraint when apply() has populated user_id.
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE v2_review_decisions SET user_id = NULL")
            cur.execute("UPDATE v2_image_metric_confirmations SET user_id = NULL")
            cur.execute("UPDATE v2_ingest_batches SET user_id = NULL")
            cur.execute("DELETE FROM v2_image_metric_confirmations")
            cur.execute("DELETE FROM v2_ingest_batches")
            cur.execute("DELETE FROM admin_audit_log")
            cur.execute("DELETE FROM auth_legacy_aliases")
            cur.execute("DELETE FROM auth_sessions")
            cur.execute("DELETE FROM auth_users")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_apply_persists_user_id_across_connections(cli, seeded):
    """After apply() returns, user_id is visible on a fresh connection.

    This is the prod-failure-mode test: the script's UPDATEs must commit
    durably so that subsequent reads (from any connection) see the change.
    """
    db = seeded["db"]
    expected_user_id = seeded["user_id"]

    counts = cli.apply(db)

    # apply() should report each mapped row updated.
    assert counts == {
        "v2_review_decisions": 1,
        "v2_image_metric_confirmations": 1,
        "v2_ingest_batches": 1,
    }, f"unexpected per-table counts: {counts}"

    # Critical assertion — read on a NEW connection (separate from the one
    # apply() used). If the UPDATEs were rolled back, user_id is still NULL.
    rd_rows = db.query(
        "SELECT user_id::text AS uid FROM v2_review_decisions WHERE fact_id = %s",
        (seeded["fact_id"],),
    )
    assert rd_rows[0]["uid"] == expected_user_id, (
        "v2_review_decisions.user_id not persisted after apply()"
    )

    imc_rows = db.query(
        "SELECT user_id::text AS uid FROM v2_image_metric_confirmations WHERE img_id = %s",
        (seeded["img_id"],),
    )
    assert imc_rows[0]["uid"] == expected_user_id, (
        "v2_image_metric_confirmations.user_id not persisted after apply()"
    )

    ib_rows = db.query(
        "SELECT user_id::text AS uid FROM v2_ingest_batches WHERE batch_id = %s",
        (seeded["batch_id"],),
    )
    assert ib_rows[0]["uid"] == expected_user_id, (
        "v2_ingest_batches.user_id not persisted after apply()"
    )

    # Unmapped row stays NULL (no alias for _OTHER_REVIEWER).
    rd2_rows = db.query(
        "SELECT user_id FROM v2_review_decisions WHERE fact_id = %s",
        (seeded["fact2_id"],),
    )
    assert rd2_rows[0]["user_id"] is None, "unmapped reviewer row should not be touched"


def test_preview_does_not_write(cli, seeded):
    """preview() reports counts but leaves user_id NULL."""
    db = seeded["db"]

    counts = cli.preview(db)
    assert counts == {
        "v2_review_decisions": 1,
        "v2_image_metric_confirmations": 1,
        "v2_ingest_batches": 1,
    }

    rd_rows = db.query(
        "SELECT user_id FROM v2_review_decisions WHERE fact_id = %s",
        (seeded["fact_id"],),
    )
    assert rd_rows[0]["user_id"] is None
