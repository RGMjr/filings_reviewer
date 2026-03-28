"""
Company-Ticker Mapping — Resolve ticker symbols to company metadata.

Provides a static registry of target companies with their display names,
plus a FMP API fallback for unknown tickers.

Usage:
    >>> from src.infra.company_mapping import get_company_info, CompanyInfo
    >>> info = get_company_info("CRM")
    >>> info.company_name
    'Salesforce'
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompanyInfo:
    """Metadata for a publicly traded company."""

    ticker: str
    company_name: str
    cik: str | None = None  # SEC Central Index Key (optional)
    sector: str | None = None


# Static registry — 10 target companies from the transcript research spike.
# These are the companies with annotated gold standard transcripts.
_COMPANY_MAP: dict[str, CompanyInfo] = {
    "ADBE": CompanyInfo("ADBE", "Adobe", sector="SaaS"),
    "ADSK": CompanyInfo("ADSK", "Autodesk", sector="SaaS"),
    "CRM": CompanyInfo("CRM", "Salesforce", sector="SaaS"),
    "EA": CompanyInfo("EA", "Electronic Arts", sector="Gaming"),
    "GDDY": CompanyInfo("GDDY", "GoDaddy", sector="SaaS"),
    "INTU": CompanyInfo("INTU", "Intuit", sector="SaaS"),
    "META": CompanyInfo("META", "Meta Platforms", sector="Consumer Tech"),
    "MSFT": CompanyInfo("MSFT", "Microsoft", sector="SaaS"),
    "PYPL": CompanyInfo("PYPL", "PayPal", sector="Fintech"),
    "TMUS": CompanyInfo("TMUS", "T-Mobile", sector="Telecom"),
}


def get_company_info(ticker: str) -> CompanyInfo | None:
    """
    Look up company metadata by ticker symbol.

    Returns None if the ticker is not in the static registry.
    Tickers are case-insensitive.

    Args:
        ticker: Stock ticker symbol (e.g., "CRM", "crm")

    Returns:
        CompanyInfo if found, None otherwise
    """
    return _COMPANY_MAP.get(ticker.upper())


def list_known_tickers() -> list[str]:
    """Return all tickers in the static registry, sorted."""
    return sorted(_COMPANY_MAP.keys())
