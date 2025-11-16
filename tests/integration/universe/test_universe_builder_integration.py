"""
Integration tests for UniverseBuilder.

These tests use a real PostgreSQL database and fixture data to validate
the end-to-end behavior of UniverseBuilder.

Requirements:
- PostgreSQL database (TEST_DATABASE_URL environment variable)
- Database schema already created (run sql/01_create_schema.sql)
"""

import pytest

from src.universe.universe_builder import UniverseBuilder


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestUniverseBuilderIntegration:
    """Integration tests for UniverseBuilder with real database."""

    def test_build_universe_with_fixtures(
        self, clean_db, mock_sec_client_with_fixtures, all_fixtures
    ):
        """
        Test building universe with all fixture data.

        This is the main end-to-end integration test.
        """
        # Create UniverseBuilder
        builder = UniverseBuilder(
            sec_client=mock_sec_client_with_fixtures, db=clean_db
        )

        # Build universe
        in_scope_count = builder.build_universe("2015-01-01", "2025-12-31")

        # Should have 2 in-scope filings (Shopify + Datadog)
        # dMY SPAC should be excluded
        assert in_scope_count == 2

        # Verify companies were created
        shopify = clean_db.get_company_by_cik("0001419612")
        assert shopify is not None
        assert shopify["company_name"] == "Shopify Inc."
        assert shopify["ticker"] == "SHOP"

        datadog = clean_db.get_company_by_cik("0001561550")
        assert datadog is not None
        assert datadog["company_name"] == "Datadog, Inc."

        dmy = clean_db.get_company_by_cik("0001772757")
        assert dmy is not None
        assert dmy["company_name"] == "dMY Technology Group, Inc. Acquisition Corp"

        # Verify filings were created with correct classifications
        filings = clean_db.query("SELECT * FROM filings ORDER BY filing_date")
        assert len(filings) == 3

        # Check Shopify (first filing)
        shopify_filing = filings[0]
        assert shopify_filing["cik"] == "0001419612"
        assert shopify_filing["form_type"] == "S-1"
        assert shopify_filing["is_in_scope_phase1"] is True
        assert shopify_filing["is_spac"] is False
        assert shopify_filing["is_first_time_issuer"] is True

        # Check Datadog (second filing)
        datadog_filing = filings[1]
        assert datadog_filing["cik"] == "0001561550"
        assert datadog_filing["form_type"] == "F-1"
        assert datadog_filing["is_in_scope_phase1"] is True
        assert datadog_filing["is_spac"] is False

        # Check dMY SPAC (third filing)
        dmy_filing = filings[2]
        assert dmy_filing["cik"] == "0001772757"
        assert dmy_filing["is_in_scope_phase1"] is False  # Excluded!
        assert dmy_filing["is_spac"] is True  # Detected as SPAC

    def test_coverage_stats(self, clean_db, mock_sec_client_with_fixtures):
        """Test coverage statistics after building universe."""
        builder = UniverseBuilder(
            sec_client=mock_sec_client_with_fixtures, db=clean_db
        )

        builder.build_universe("2015-01-01", "2025-12-31")

        stats = builder.get_coverage_stats()

        # Verify stats
        assert stats["total_companies"] == 3
        assert stats["total_filings"] == 3
        assert stats["in_scope_filings"] == 2  # Shopify + Datadog
        assert stats["spac_count"] == 1  # dMY
        assert stats["first_time_issuer_count"] == 3  # All three are first-time

        # Check by-year breakdown
        assert 2015 in stats["by_year"]
        assert stats["by_year"][2015] == 1  # Shopify
        assert stats["by_year"][2019] == 1  # Datadog
        assert stats["by_year"][2020] == 1  # dMY

    def test_idempotency(self, clean_db, mock_sec_client_with_fixtures):
        """Test that re-running build_universe doesn't create duplicates."""
        builder = UniverseBuilder(
            sec_client=mock_sec_client_with_fixtures, db=clean_db
        )

        # Run twice
        count1 = builder.build_universe("2015-01-01", "2025-12-31")
        count2 = builder.build_universe("2015-01-01", "2025-12-31")

        # Same count both times
        assert count1 == 2
        assert count2 == 2

        # Still only 3 companies
        companies = clean_db.query("SELECT * FROM companies")
        assert len(companies) == 3

        # Still only 3 filings
        filings = clean_db.query("SELECT * FROM filings")
        assert len(filings) == 3


class TestIndividualFixtures:
    """Test each fixture individually to validate classification."""

    def test_shopify_classification(self, clean_db, fixture_shopify):
        """Test Shopify fixture classification."""
        from tests.integration.conftest import metadata_to_filing_metadata

        filing_metadata = metadata_to_filing_metadata(fixture_shopify)
        mock_client = pytest.importorskip(
            "src.infra.sec_client"
        ).MockSECClient(mock_filings=[filing_metadata])

        builder = UniverseBuilder(sec_client=mock_client, db=clean_db)
        in_scope_count = builder.build_universe("2015-01-01", "2015-12-31")

        # Should be in scope
        assert in_scope_count == 1

        # Check database
        filing = clean_db.query(
            "SELECT * FROM filings WHERE accession_number = %(acc)s",
            {"acc": fixture_shopify["accession_number"]},
        )[0]

        expected = fixture_shopify["expected_classification"]
        assert filing["is_spac"] == expected["is_spac"]
        assert filing["is_first_time_issuer"] == expected["is_first_time_issuer"]
        assert filing["is_in_scope_phase1"] == expected["is_in_scope_phase1"]

    def test_datadog_classification(self, clean_db, fixture_datadog):
        """Test Datadog (F-1) fixture classification."""
        from tests.integration.conftest import metadata_to_filing_metadata

        filing_metadata = metadata_to_filing_metadata(fixture_datadog)
        mock_client = pytest.importorskip(
            "src.infra.sec_client"
        ).MockSECClient(mock_filings=[filing_metadata])

        builder = UniverseBuilder(sec_client=mock_client, db=clean_db)
        in_scope_count = builder.build_universe("2019-01-01", "2019-12-31")

        # Should be in scope (F-1 is included)
        assert in_scope_count == 1

        # Check form type
        filing = clean_db.query(
            "SELECT * FROM filings WHERE accession_number = %(acc)s",
            {"acc": fixture_datadog["accession_number"]},
        )[0]

        assert filing["form_type"] == "F-1"
        assert filing["is_in_scope_phase1"] is True

    def test_spac_exclusion(self, clean_db, fixture_spac):
        """Test SPAC fixture is correctly excluded."""
        from tests.integration.conftest import metadata_to_filing_metadata

        filing_metadata = metadata_to_filing_metadata(fixture_spac)
        mock_client = pytest.importorskip(
            "src.infra.sec_client"
        ).MockSECClient(mock_filings=[filing_metadata])

        builder = UniverseBuilder(sec_client=mock_client, db=clean_db)
        in_scope_count = builder.build_universe("2020-01-01", "2020-12-31")

        # Should NOT be in scope
        assert in_scope_count == 0

        # But should still be in database
        filing = clean_db.query(
            "SELECT * FROM filings WHERE accession_number = %(acc)s",
            {"acc": fixture_spac["accession_number"]},
        )[0]

        assert filing["is_spac"] is True
        assert filing["is_in_scope_phase1"] is False


class TestDatabaseConstraints:
    """Test that database constraints work as expected."""

    def test_unique_cik_constraint(self, clean_db):
        """Test that CIK must be unique in companies table."""
        # Insert first company
        clean_db.upsert_company(cik="0001234567", company_name="Test Company 1")

        # Upsert with same CIK but different name should update
        company_id = clean_db.upsert_company(
            cik="0001234567", company_name="Test Company Updated"
        )

        # Should still be only one company
        companies = clean_db.query(
            "SELECT * FROM companies WHERE cik = '0001234567'"
        )
        assert len(companies) == 1
        assert companies[0]["company_name"] == "Test Company Updated"

    def test_unique_filing_constraint(self, clean_db):
        """Test that (company_id, accession_number) must be unique."""
        # Create company
        company_id = clean_db.upsert_company(
            cik="0001234567", company_name="Test Company"
        )

        # Insert filing
        filing_id1 = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-20-000001",
            form_type="S-1",
            filing_date="2020-01-01",
            sec_html_url="https://example.com/filing1.htm",
        )

        # Upsert with same company_id and accession should update
        filing_id2 = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-20-000001",
            form_type="S-1/A",  # Changed to amendment
            filing_date="2020-01-15",
            sec_html_url="https://example.com/filing1a.htm",
        )

        # Should be same filing (updated)
        assert filing_id1 == filing_id2

        # Should still be only one filing
        filings = clean_db.query(
            "SELECT * FROM filings WHERE accession_number = '0001234567-20-000001'"
        )
        assert len(filings) == 1
        assert filings[0]["form_type"] == "S-1/A"
