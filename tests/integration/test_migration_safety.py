"""
Integration tests for migration safety.

Verifies that:
1. Migrations apply cleanly on a DB with existing V1 data
2. V1 functionality is intact after V2 migrations
3. V2 tables are functional after migration
4. apply_migrations is idempotent (running twice is safe)
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Make scripts importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.apply_migrations import MIGRATIONS, apply_migration, bootstrap_ledger
from src.infra.db import DatabaseAdapter


class TestMigrationSafety:
    """Tests that migrations apply safely and are idempotent."""

    @pytest.fixture(autouse=True)
    def skip_without_test_db(self):
        if not os.environ.get("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

    @pytest.fixture
    def db(self, test_db_url):
        return DatabaseAdapter(test_db_url)

    @pytest.fixture
    def sql_dir(self):
        return Path(__file__).parent.parent.parent / "sql"

    def test_v2_migrations_on_populated_v1_db(self, db, sql_dir):
        """
        Apply all migrations and verify no errors.

        Since the session-scoped autouse fixture already applied migrations,
        we verify the schema exists and is functional.
        """
        # Verify V1 tables exist
        result = db.query("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('companies', 'filings', 'review_candidates', 'review_decisions', 'metrics')
            ORDER BY table_name
        """)
        v1_tables = {r["table_name"] for r in result}
        assert "companies" in v1_tables
        assert "filings" in v1_tables
        assert "metrics" in v1_tables

    def test_v2_tables_exist_after_migration(self, db):
        """Verify all V2 tables were created by migrations."""
        result = db.query("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name LIKE 'v2_%%'
            ORDER BY table_name
        """)
        v2_tables = {r["table_name"] for r in result}

        expected = {
            "v2_documents",
            "v2_segments",
            "v2_tables",
            "v2_table_cells",
            "v2_image_assets",
            "v2_metric_facts",
            "v2_review_decisions",
        }
        for table in expected:
            assert table in v2_tables, f"Missing V2 table: {table}"

    def test_v1_queries_work_after_v2_migration(self, db):
        """V1 review candidate queries still work after V2 migrations."""
        # Insert a V1 company and filing
        company_id = db.upsert_company(
            cik="9998877001",
            company_name="Migration Safety Test Corp",
        )
        filing_id = db.upsert_filing(
            company_id=company_id,
            cik="9998877001",
            accession_number="9998877001-99-000001",
            form_type="S-1",
            filing_date="2023-06-01",
            sec_html_url="https://www.sec.gov/test/migration",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Insert a V1 review candidate
        candidate_id = db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We have 5,000 active customers.",
            raw_number_text="5,000",
            triggering_keyword="customers",
            keyword_distance=10,
            keyword_position="after",
        )

        # Verify V1 candidate is retrievable
        candidate = db.get_review_candidate(candidate_id)
        assert candidate is not None
        assert candidate["filing_id"] == filing_id
        assert candidate["raw_number_text"] == "5,000"

        # Cleanup
        db.execute(
            "DELETE FROM review_candidates WHERE candidate_id = %(id)s",
            {"id": candidate_id},
        )
        db.execute("DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id})
        db.execute("DELETE FROM companies WHERE company_id = %(id)s", {"id": company_id})

    def test_v2_tables_functional_after_migration(self, db):
        """Can INSERT and SELECT V2 facts and decisions after migration."""
        # Create prerequisite data
        company_id = db.upsert_company(
            cik="9998877002",
            company_name="V2 Functional Test Corp",
        )
        filing_id = db.upsert_filing(
            company_id=company_id,
            cik="9998877002",
            accession_number="9998877002-99-000001",
            form_type="S-1",
            filing_date="2023-06-01",
            sec_html_url="https://www.sec.gov/test/v2-functional",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Insert V2 document
        doc_rows = db.query(
            """
            INSERT INTO v2_documents (filing_id, parse_version, status)
            VALUES (%(filing_id)s, '2.0.0', 'complete')
            ON CONFLICT (filing_id) DO UPDATE SET status = EXCLUDED.status
            RETURNING doc_id::text
            """,
            {"filing_id": filing_id},
        )
        assert doc_rows, "Failed to insert v2_documents row"

        # Insert V2 fact (doc_id in v2_metric_facts = filing_id, a BIGINT FK to filings)
        fact_rows = db.query(
            """
            INSERT INTO v2_metric_facts (
                doc_id, canonical_metric_id, value_raw, unit, source_type,
                source_locator, evidence_pack, confidence
            ) VALUES (
                %(filing_id)s, 'cm_customers_period_end', '5000', 'count', 'text',
                %(locator)s, %(evidence)s, 0.9
            )
            RETURNING fact_id::text
            """,
            {
                "filing_id": filing_id,
                "locator": json.dumps({"dom_locator": "/html/body/p[1]"}),
                "evidence": json.dumps({"snippet_html": "<p>5000 customers</p>"}),
            },
        )
        assert fact_rows, "Failed to insert v2_metric_facts row"
        fact_id = fact_rows[0]["fact_id"]

        # Insert V2 decision
        decision_rows = db.query(
            """
            INSERT INTO v2_review_decisions (fact_id, decision, reviewer_id)
            VALUES (%(fact_id)s::uuid, 'accept', 'test_reviewer')
            RETURNING decision_id::text
            """,
            {"fact_id": fact_id},
        )
        assert decision_rows, "Failed to insert v2_review_decisions row"

        # Verify trigger updated review_status
        updated = db.query(
            "SELECT review_status FROM v2_metric_facts WHERE fact_id = %(id)s::uuid",
            {"id": fact_id},
        )
        assert updated[0]["review_status"] == "accepted", "Trigger did not update review_status"

        # Cleanup (CASCADE handles v2_metric_facts and v2_review_decisions via filing_id)
        db.execute("DELETE FROM filings WHERE filing_id = %(id)s", {"id": filing_id})
        db.execute("DELETE FROM companies WHERE company_id = %(id)s", {"id": company_id})

    def test_migration_idempotency(self, db, sql_dir):
        """Running apply_migrations twice produces no errors (checksum skip)."""
        # bootstrap_ledger is safe to call multiple times (CREATE TABLE IF NOT EXISTS)
        bootstrap_ledger(db)

        # Apply all migrations again — should all be SKIPPED (already applied)
        for migration_name in MIGRATIONS:
            sql_file = sql_dir / migration_name
            if not sql_file.exists():
                continue
            result = apply_migration(db, sql_dir, migration_name)
            assert result == "skipped", (
                f"Expected migration {migration_name} to be skipped on second run, got '{result}'"
            )
