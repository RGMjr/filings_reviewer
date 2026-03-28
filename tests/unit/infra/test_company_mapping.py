"""
Unit tests for src/infra/company_mapping.py.

Tests cover:
- Known ticker lookup
- Case-insensitive lookup
- Unknown ticker returns None
- list_known_tickers sorted output
"""

from __future__ import annotations

from src.infra.company_mapping import CompanyInfo, get_company_info, list_known_tickers

# ============================================================================
# CompanyInfo Tests
# ============================================================================


class TestCompanyInfo:
    def test_create_with_required_fields(self):
        """CompanyInfo can be created with just ticker and name."""
        info = CompanyInfo(ticker="TEST", company_name="Test Corp")
        assert info.ticker == "TEST"
        assert info.company_name == "Test Corp"
        assert info.cik is None
        assert info.sector is None

    def test_create_with_all_fields(self):
        """CompanyInfo stores all optional fields."""
        info = CompanyInfo(
            ticker="CRM",
            company_name="Salesforce",
            cik="0001108524",
            sector="SaaS",
        )
        assert info.cik == "0001108524"
        assert info.sector == "SaaS"


# ============================================================================
# get_company_info Tests
# ============================================================================


class TestGetCompanyInfo:
    def test_get_known_ticker(self):
        """Known ticker returns correct CompanyInfo."""
        info = get_company_info("CRM")
        assert info is not None
        assert info.ticker == "CRM"
        assert info.company_name == "Salesforce"
        assert info.sector == "SaaS"

    def test_get_known_ticker_adobe(self):
        """ADBE maps to Adobe."""
        info = get_company_info("ADBE")
        assert info is not None
        assert info.company_name == "Adobe"

    def test_case_insensitive_lookup_lower(self):
        """Lowercase ticker resolves correctly."""
        info = get_company_info("adbe")
        assert info is not None
        assert info.company_name == "Adobe"

    def test_case_insensitive_lookup_mixed(self):
        """Mixed-case ticker resolves correctly."""
        info = get_company_info("Crm")
        assert info is not None
        assert info.company_name == "Salesforce"

    def test_unknown_ticker_returns_none(self):
        """Unknown ticker returns None without raising."""
        result = get_company_info("ZZZZZ")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string ticker returns None."""
        result = get_company_info("")
        assert result is None

    def test_all_ten_companies_present(self):
        """All 10 target companies are in the registry."""
        expected = ["ADBE", "ADSK", "CRM", "EA", "GDDY", "INTU", "META", "MSFT", "PYPL", "TMUS"]
        for ticker in expected:
            assert get_company_info(ticker) is not None, f"Missing: {ticker}"


# ============================================================================
# list_known_tickers Tests
# ============================================================================


class TestListKnownTickers:
    def test_returns_sorted_list(self):
        """Tickers are returned in sorted order."""
        tickers = list_known_tickers()
        assert tickers == sorted(tickers)

    def test_correct_count(self):
        """Returns all 10 registered tickers."""
        tickers = list_known_tickers()
        assert len(tickers) == 10

    def test_returns_list_type(self):
        """Return type is a list."""
        result = list_known_tickers()
        assert isinstance(result, list)

    def test_contains_expected_tickers(self):
        """Known tickers appear in the list."""
        tickers = list_known_tickers()
        assert "CRM" in tickers
        assert "ADBE" in tickers
        assert "MSFT" in tickers
