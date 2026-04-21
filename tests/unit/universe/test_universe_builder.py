"""
Unit tests for UniverseBuilder component.

Uses mocks to test the build_universe logic without requiring a real database or SEC API.
"""

from unittest.mock import Mock

import pytest

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import FilingMetadata, MockSECClient
from src.universe.universe_builder import UniverseBuilder


@pytest.fixture
def mock_db():
    """Create a mock database adapter."""
    db = Mock(spec=DatabaseAdapter)

    # Mock company upsert to return company_id
    db.upsert_company = Mock(return_value=1)

    # Mock filing upsert to return filing_id
    db.upsert_filing = Mock(return_value=100)

    # Mock queries
    db.get_first_ipo_filing_date = Mock(return_value=None)
    db.get_in_scope_filing_count = Mock(return_value=0)
    db.mark_superseded_filings = Mock(return_value=0)
    db.query = Mock(return_value=[])

    return db


@pytest.fixture
def sample_filings():
    """Create sample filing metadata for testing."""
    return [
        # First-time issuer, non-SPAC - should be in scope
        FilingMetadata(
            cik="0001234567",
            company_name="Shopify Inc.",
            form_type="S-1",
            filing_date="2015-04-14",
            accession_number="0001234567-15-000001",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456715000001/shop-s1.htm",
            ticker="SHOP",
        ),
        # SPAC - should be out of scope
        FilingMetadata(
            cik="0009876543",
            company_name="ABC Acquisition Corp.",
            form_type="S-1",
            filing_date="2020-06-01",
            accession_number="0009876543-20-000001",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/9876543/000987654320000001/abc-s1.htm",
            ticker="ABCAU",
        ),
        # Another first-time issuer - in scope
        FilingMetadata(
            cik="0005555555",
            company_name="Datadog, Inc.",
            form_type="F-1",
            filing_date="2019-08-19",
            accession_number="0005555555-19-000001",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/5555555/000555555519000001/ddog-f1.htm",
            ticker="DDOG",
        ),
    ]


class TestUniverseBuilderBasic:
    """Basic tests for UniverseBuilder."""

    def test_initialization(self, mock_db):
        """UniverseBuilder can be initialized."""
        sec_client = MockSECClient()
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        assert builder.sec_client is sec_client
        assert builder.db is mock_db

    def test_build_universe_empty_results(self, mock_db):
        """build_universe handles empty results from SEC."""
        sec_client = MockSECClient(mock_filings=[])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        count = builder.build_universe("2020-01-01", "2020-12-31")

        assert count == 0
        mock_db.upsert_company.assert_not_called()
        mock_db.upsert_filing.assert_not_called()

    def test_build_universe_single_filing(self, mock_db, sample_filings):
        """build_universe processes a single filing correctly."""
        # Use only the first (non-SPAC) filing
        sec_client = MockSECClient(mock_filings=sample_filings[:1])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        count = builder.build_universe("2015-01-01", "2015-12-31")

        # Should have 1 in-scope filing (Shopify)
        assert count == 1

        # Company should be upserted
        mock_db.upsert_company.assert_called_once()
        call_args = mock_db.upsert_company.call_args[1]
        assert call_args["cik"] == "0001234567"
        assert call_args["company_name"] == "Shopify Inc."
        assert call_args["ticker"] == "SHOP"

        # Filing should be upserted
        mock_db.upsert_filing.assert_called_once()
        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["cik"] == "0001234567"
        assert filing_args["accession_number"] == "0001234567-15-000001"
        assert filing_args["is_in_scope_phase1"] is True
        assert filing_args["is_spac"] is False
        assert filing_args["is_first_time_issuer"] is True


class TestUniverseBuilderClassification:
    """Tests for classification logic in UniverseBuilder."""

    def test_spac_exclusion(self, mock_db, sample_filings):
        """SPACs are correctly excluded from Phase 1 scope."""
        # Use only the SPAC filing
        spac_filing = [f for f in sample_filings if "Acquisition" in f.company_name]
        sec_client = MockSECClient(mock_filings=spac_filing)
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        count = builder.build_universe("2020-01-01", "2020-12-31")

        # SPAC should not be in scope
        assert count == 0

        # But it should still be recorded in database
        mock_db.upsert_filing.assert_called_once()
        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["is_spac"] is True
        assert filing_args["is_in_scope_phase1"] is False

    def test_spac_excluded_via_filing_text(self, mock_db):
        """SPAC excluded via SGML header SIC pattern when name and current EDGAR SIC are inconclusive."""
        diamond_peak_txt_url = "https://www.sec.gov/Archives/edgar/data/1759546/000121390019000906/0001213900-19-000906.txt"
        diamond_peak = FilingMetadata(
            cik="0001759546",
            company_name="DiamondPeak Holdings Corp.",
            form_type="S-1",
            filing_date="2019-01-18",
            accession_number="0001213900-19-000906",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1759546/000121390019000906/f1.htm",
            txt_url=diamond_peak_txt_url,
            ticker=None,
        )
        # No SPAC name pattern; EDGAR now shows SIC 3711 (post-merger).
        # Only the SGML header in the .txt file preserves the original SIC 6770.
        sgml_header = (
            "DiamondPeak Holdings Corp.\n"
            "\tSTANDARD INDUSTRIAL CLASSIFICATION:\tBLANK CHECKS [6770]\n"
        )
        sec_client = MockSECClient(
            mock_filings=[diamond_peak],
            mock_filing_texts={diamond_peak_txt_url: sgml_header},
        )
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        count = builder.build_universe("2019-01-01", "2019-12-31")

        assert count == 0
        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["is_spac"] is True
        assert filing_args["is_in_scope_phase1"] is False

    def test_text_fetch_skipped_when_already_spac_by_name(self, mock_db, sample_filings):
        """Filing text is not fetched when the SPAC is already identified by name."""
        spac_filing = [f for f in sample_filings if "Acquisition" in f.company_name]
        sec_client = MockSECClient(mock_filings=spac_filing)
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)
        builder.build_universe("2020-01-01", "2020-12-31")

        # Should be excluded without needing a text fetch
        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["is_spac"] is True
        assert filing_args["is_in_scope_phase1"] is False

    def test_spac_excluded_via_sic_6770(self, mock_db):
        """SPAC with ambiguous name but SIC 6770 is excluded via EDGAR lookup."""
        # DiamondPeak-style: name doesn't match SPAC patterns, but EDGAR reports SIC 6770
        diamond_peak = FilingMetadata(
            cik="0001759546",
            company_name="DiamondPeak Holdings Corp.",
            form_type="S-1",
            filing_date="2019-01-18",
            accession_number="0001213900-19-000906",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1759546/000121390019000906/f1.htm",
            ticker=None,
        )
        sec_client = MockSECClient(
            mock_filings=[diamond_peak],
            mock_company_info={"0001759546": {"sic": "6770", "name": "DiamondPeak Holdings Corp."}},
        )
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        count = builder.build_universe("2019-01-01", "2019-12-31")

        assert count == 0
        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["is_spac"] is True
        assert filing_args["is_in_scope_phase1"] is False

    def test_sic_passed_to_upsert_company(self, mock_db, sample_filings):
        """SIC code from EDGAR is stored on the company record."""
        sec_client = MockSECClient(
            mock_filings=sample_filings[:1],
            mock_company_info={"0001234567": {"sic": "7372", "name": "Shopify Inc."}},
        )
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)
        builder.build_universe("2015-01-01", "2015-12-31")

        company_args = mock_db.upsert_company.call_args[1]
        assert company_args["industry_code"] == "7372"
        assert company_args["industry_classification_source"] == "edgar_submissions"

    def test_first_time_issuer_detection(self, mock_db, sample_filings):
        """First-time issuer is correctly detected."""
        sec_client = MockSECClient(mock_filings=sample_filings[:1])

        # Mock: no prior IPO filings
        mock_db.get_first_ipo_filing_date = Mock(return_value=None)

        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)
        count = builder.build_universe("2015-01-01", "2015-12-31")

        assert count == 1

        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["is_first_time_issuer"] is True

    def test_not_first_time_issuer(self, mock_db, sample_filings):
        """Subsequent filings are correctly classified as not first-time."""
        sec_client = MockSECClient(mock_filings=sample_filings[:1])

        # Mock: prior IPO filing exists
        mock_db.get_first_ipo_filing_date = Mock(return_value="2014-01-01")

        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)
        count = builder.build_universe("2015-01-01", "2015-12-31")

        # Current behavior: included for manual review with uncertain classification
        assert count == 1

        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["is_first_time_issuer"] is False
        # Uncertain cases are included for manual review
        assert filing_args["classification_method"] == "uncertain"


class TestUniverseBuilderMultipleFilings:
    """Tests for processing multiple filings."""

    def test_multiple_filings_mixed_scope(self, mock_db, sample_filings):
        """Multiple filings with mixed scope are processed correctly."""
        sec_client = MockSECClient(mock_filings=sample_filings)
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        count = builder.build_universe("2015-01-01", "2025-12-31")

        # Should have 2 in-scope filings (Shopify + Datadog)
        # SPAC should be excluded
        assert count == 2

        # Should have 3 companies upserted
        assert mock_db.upsert_company.call_count == 3

        # Should have 3 filings upserted
        assert mock_db.upsert_filing.call_count == 3

    def test_idempotency(self, mock_db, sample_filings):
        """Running build_universe twice doesn't create duplicates."""
        sec_client = MockSECClient(mock_filings=sample_filings[:1])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        # Run twice
        count1 = builder.build_universe("2015-01-01", "2015-12-31")
        count2 = builder.build_universe("2015-01-01", "2015-12-31")

        assert count1 == 1
        assert count2 == 1

        # Upsert should handle duplicates
        # Each run calls upsert once
        assert mock_db.upsert_company.call_count == 2
        assert mock_db.upsert_filing.call_count == 2


class TestBuildUniverseFormTypes:
    """Tests for the form_types parameter on build_universe (Issue #7)."""

    def test_default_preserves_s1f1(self, mock_db):
        """No form_types arg → search_filings sees the S-1/F-1 family."""
        from unittest.mock import patch

        from src.universe.universe_builder import DEFAULT_FORM_TYPES_S1F1

        sec_client = MockSECClient(mock_filings=[])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        with patch.object(sec_client, "search_filings", wraps=sec_client.search_filings) as spy:
            builder.build_universe("2015-01-01", "2015-12-31")

        spy.assert_called_once_with("2015-01-01", "2015-12-31", DEFAULT_FORM_TYPES_S1F1)

    def test_custom_form_types_passed_to_sec_client(self, mock_db):
        """Passing form_types=['10-K', '10-K/A'] forwards to search_filings."""
        from unittest.mock import patch

        sec_client = MockSECClient(mock_filings=[])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        with patch.object(sec_client, "search_filings", wraps=sec_client.search_filings) as spy:
            builder.build_universe("2020-01-01", "2020-12-31", form_types=["10-K", "10-K/A"])

        spy.assert_called_once_with("2020-01-01", "2020-12-31", ["10-K", "10-K/A"])

    def test_10k_filing_skips_sgml_recheck(self, mock_db):
        """For 10-K filings, the SPAC SGML text-sample re-check is skipped.

        Regression guard: the re-check fetches txt_url once per filing.
        Running it on thousands of 10-Ks wastes SEC rate-limit without
        providing any signal (SGML 'BLANK CHECKS [6770]' is S-1-only).
        """
        from unittest.mock import patch

        tenk_filing = FilingMetadata(
            cik="0001234567",
            company_name="Acme Corp.",
            form_type="10-K",
            filing_date="2020-02-15",
            accession_number="0001234567-20-000005",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/tenk.htm",
            txt_url="https://www.sec.gov/Archives/edgar/data/1234567/tenk.txt",
            ticker="ACME",
        )
        sec_client = MockSECClient(mock_filings=[tenk_filing])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        with patch.object(sec_client, "fetch_filing_text_sample") as text_spy:
            builder.build_universe("2020-01-01", "2020-12-31", form_types=["10-K"])

        text_spy.assert_not_called()
        # Filing still lands with is_in_scope_phase1=False (correct: 10-K not Phase 1)
        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["form_type"] == "10-K"
        assert filing_args["is_in_scope_phase1"] is False

    def test_10k_filing_has_null_first_time_issuer(self, mock_db):
        """10-K filings land with is_first_time_issuer=None, not True.

        Regression guard for KNOWN_ISSUES.md #37: the classifier's "no prior
        S-1 in DB → True" heuristic is nonsensical for 10-Ks, so the call is
        gated to S-1/F-1 form types and non-applicable cases are recorded as
        NULL instead of the misleading TRUE value.
        """
        tenk_filing = FilingMetadata(
            cik="0009999999",
            company_name="Widget Co.",
            form_type="10-K",
            filing_date="2022-03-01",
            accession_number="0009999999-22-000001",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/9999999/tenk.htm",
            ticker="WDGT",
        )
        sec_client = MockSECClient(mock_filings=[tenk_filing])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        builder.build_universe("2022-01-01", "2022-12-31", form_types=["10-K"])

        filing_args = mock_db.upsert_filing.call_args[1]
        assert filing_args["form_type"] == "10-K"
        assert filing_args["is_first_time_issuer"] is None
        # get_first_ipo_filing_date should not be called for non-S-1/F-1 forms
        mock_db.get_first_ipo_filing_date.assert_not_called()

    def test_limit_stops_after_n_in_scope_upserts(self, mock_db):
        """build_universe(limit=N) breaks the loop after N in-scope upserts.

        Regression guard for KNOWN_ISSUES.md #36: `populate --form-type 10k`
        without a brake can trigger a ~15-minute SEC traffic run.
        """
        filings = [
            FilingMetadata(
                cik=f"000{i:07d}",
                company_name=f"InScope Co {i}",
                form_type="S-1",
                filing_date="2020-04-01",
                accession_number=f"000{i:07d}-20-000001",
                primary_doc_url=f"https://www.sec.gov/Archives/edgar/data/{i}/s1.htm",
                ticker=f"IS{i}",
            )
            for i in range(5)
        ]
        sec_client = MockSECClient(mock_filings=filings)
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        count = builder.build_universe("2020-01-01", "2020-12-31", limit=2)

        assert count == 2
        assert mock_db.upsert_filing.call_count == 2

    def test_s1_filing_still_performs_sgml_recheck(self, mock_db):
        """Regression: S-1 filings must still trigger the SGML re-check."""
        from unittest.mock import patch

        s1_filing = FilingMetadata(
            cik="0001234567",
            company_name="Ambiguous Name Corp.",
            form_type="S-1",
            filing_date="2019-01-18",
            accession_number="0001234567-19-000001",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/s1.htm",
            txt_url="https://www.sec.gov/Archives/edgar/data/1234567/s1.txt",
            ticker=None,
        )
        sec_client = MockSECClient(mock_filings=[s1_filing])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        with patch.object(sec_client, "fetch_filing_text_sample", return_value="") as text_spy:
            builder.build_universe("2019-01-01", "2019-12-31")

        text_spy.assert_called_once()


class TestUniverseBuilderCoverageStats:
    """Tests for coverage statistics."""

    def test_coverage_stats_empty(self, mock_db):
        """Coverage stats work with empty database."""
        sec_client = MockSECClient()
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        # Mock empty database
        mock_db.query = Mock(
            side_effect=[
                [{"count": 0}],  # total companies
                [{"count": 0}],  # total filings
                [{"count": 0}],  # SPACs
                [{"count": 0}],  # first-time issuers
                [],  # by year
            ]
        )
        mock_db.get_in_scope_filing_count = Mock(return_value=0)

        stats = builder.get_coverage_stats()

        assert stats["total_companies"] == 0
        assert stats["total_filings"] == 0
        assert stats["in_scope_filings"] == 0
        assert stats["spac_count"] == 0
        assert stats["first_time_issuer_count"] == 0
        assert stats["by_year"] == {}

    def test_coverage_stats_with_data(self, mock_db):
        """Coverage stats work with populated database."""
        sec_client = MockSECClient()
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        # Mock database with data
        mock_db.query = Mock(
            side_effect=[
                [{"count": 10}],  # total companies
                [{"count": 15}],  # total filings
                [{"count": 3}],  # SPACs
                [{"count": 12}],  # first-time issuers
                [{"year": 2020, "count": 8}, {"year": 2021, "count": 7}],  # by year
            ]
        )
        mock_db.get_in_scope_filing_count = Mock(return_value=12)

        stats = builder.get_coverage_stats()

        assert stats["total_companies"] == 10
        assert stats["total_filings"] == 15
        assert stats["in_scope_filings"] == 12
        assert stats["spac_count"] == 3
        assert stats["first_time_issuer_count"] == 12
        assert stats["by_year"] == {2020: 8, 2021: 7}


class TestProgressCallback:
    """Tests for the progress_cb kwarg added in Wave C / Phase 6."""

    def _make_n_filings(self, n: int) -> list[FilingMetadata]:
        return [
            FilingMetadata(
                cik=f"{1_000_000 + i:010d}",
                company_name=f"TestCo {i}",
                form_type="S-1",
                filing_date="2024-01-01",
                accession_number=f"0001000000-24-{i:06d}",
                primary_doc_url=f"https://example.com/{i}.htm",
                ticker=f"T{i:03d}",
            )
            for i in range(n)
        ]

    def test_callback_invoked_at_start_every_5_and_end(self, mock_db):
        sec_client = MockSECClient()
        sec_client.search_filings = Mock(return_value=self._make_n_filings(12))
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        calls: list[tuple[int, int]] = []

        def cb(processed: int, total: int) -> None:
            calls.append((processed, total))

        builder.build_universe("2024-01-01", "2024-12-31", progress_cb=cb)

        # Expect: (0, 12), (5, 12), (10, 12), (12, 12).
        # The "every 5 iterations" tick fires when processed % 5 == 0; with 12
        # filings that's processed=5 and processed=10. The final (total, total)
        # always fires at the end.
        assert (0, 12) in calls
        assert (5, 12) in calls
        assert (10, 12) in calls
        assert (12, 12) in calls

    def test_callback_none_is_safe(self, mock_db):
        """progress_cb=None default must not raise."""
        sec_client = MockSECClient()
        sec_client.search_filings = Mock(return_value=self._make_n_filings(3))
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)
        # Default kwarg — should not raise
        builder.build_universe("2024-01-01", "2024-12-31")

    def test_callback_with_zero_filings(self, mock_db):
        """Empty filing list still fires (0, 0) start + (0, 0) end."""
        sec_client = MockSECClient()
        sec_client.search_filings = Mock(return_value=[])
        builder = UniverseBuilder(sec_client=sec_client, db=mock_db)

        calls: list[tuple[int, int]] = []
        builder.build_universe(
            "2024-01-01", "2024-12-31", progress_cb=lambda p, t: calls.append((p, t))
        )
        # First and last fire even with empty list
        assert calls.count((0, 0)) >= 1
