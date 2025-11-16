"""
SEC EDGAR client for querying filings.

Provides a simple abstraction over the SEC EDGAR API for discovering and fetching filing metadata.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


@dataclass
class FilingMetadata:
    """
    Metadata for a single SEC filing.

    Attributes:
        cik: SEC Central Index Key
        company_name: Issuer name
        form_type: Form type (e.g., 'S-1', 'F-1')
        filing_date: Date filed (ISO format string)
        accession_number: SEC accession number
        primary_doc_url: URL to primary HTML document
        txt_url: URL to complete text filing
        ticker: Stock ticker (if available)
    """

    cik: str
    company_name: str
    form_type: str
    filing_date: str
    accession_number: str
    primary_doc_url: str
    txt_url: Optional[str] = None
    ticker: Optional[str] = None


class SECClient:
    """
    Client for querying SEC EDGAR API.

    Implements rate limiting and polite access according to SEC guidelines.
    See: https://www.sec.gov/os/webmaster-faq#code-support
    """

    BASE_URL = "https://www.sec.gov"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

    # Rate limiting: SEC requests max 10 requests per second
    MIN_REQUEST_INTERVAL = 0.11  # slightly over 100ms to be safe

    def __init__(self, user_agent: str = "filings-reviewer info@example.com"):
        """
        Initialize SEC client.

        Args:
            user_agent: User agent string for SEC requests.
                MUST include company name and contact email per SEC policy.
        """
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _make_request(self, url: str, params: Optional[dict] = None) -> dict:
        """
        Make a rate-limited request to SEC.

        Args:
            url: URL to request
            params: Query parameters

        Returns:
            JSON response as dict

        Raises:
            requests.HTTPError: If request fails
        """
        self._rate_limit()

        logger.debug(f"Requesting: {url}")
        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json()

    def search_filings(
        self,
        start_date: str,
        end_date: str,
        form_types: Optional[List[str]] = None,
    ) -> List[FilingMetadata]:
        """
        Search for filings in a date range.

        Note: This is a simplified implementation for v0.1. For production use,
        consider using the SEC's bulk data or RSS feeds for better performance.

        Args:
            start_date: Start date (ISO format: YYYY-MM-DD)
            end_date: End date (ISO format: YYYY-MM-DD)
            form_types: List of form types to include (e.g., ['S-1', 'F-1']).
                If None, defaults to ['S-1', 'S-1/A', 'F-1', 'F-1/A']

        Returns:
            List of FilingMetadata objects

        Note:
            This implementation uses the company search endpoint which may not
            be ideal for large date ranges. Consider implementing a more robust
            solution using SEC's RSS feeds or bulk data for production.
        """
        if form_types is None:
            form_types = ['S-1', 'S-1/A', 'F-1', 'F-1/A']

        # For v0.1, we'll use a simplified approach
        # In production, you'd want to use SEC's RSS feeds or bulk downloads
        logger.warning(
            "search_filings uses a simplified implementation. "
            "For large date ranges, consider using SEC RSS feeds or bulk data."
        )

        # This is a placeholder that demonstrates the interface
        # Real implementation would query SEC's company search or RSS feeds
        filings = []

        # TODO: Implement actual EDGAR querying
        # Options:
        # 1. Use SEC's RSS feeds: https://www.sec.gov/cgi-bin/browse-edgar
        # 2. Use SEC's full text search API
        # 3. Parse daily index files from https://www.sec.gov/Archives/edgar/daily-index/

        logger.info(
            f"Searching for filings: {start_date} to {end_date}, "
            f"form_types={form_types}"
        )

        return filings

    def get_filing_by_accession(
        self, cik: str, accession_number: str
    ) -> Optional[FilingMetadata]:
        """
        Get filing metadata by CIK and accession number.

        Args:
            cik: SEC Central Index Key (10 digits, zero-padded)
            accession_number: SEC accession number (format: 0000000000-00-000000)

        Returns:
            FilingMetadata or None if not found
        """
        # Normalize CIK to 10 digits with leading zeros
        cik_padded = cik.zfill(10)

        try:
            # Get company submissions data
            url = self.SUBMISSIONS_URL.format(cik=cik_padded)
            data = self._make_request(url)

            # Find the filing in recent filings
            recent = data.get("filings", {}).get("recent", {})
            accession_numbers = recent.get("accessionNumber", [])

            try:
                idx = accession_numbers.index(accession_number)
            except ValueError:
                logger.warning(
                    f"Accession number {accession_number} not found for CIK {cik}"
                )
                return None

            # Extract filing metadata
            form_types = recent.get("form", [])
            filing_dates = recent.get("filingDate", [])
            primary_docs = recent.get("primaryDocument", [])

            # Construct URLs
            accession_no_dashes = accession_number.replace("-", "")
            primary_doc_url = (
                f"{self.BASE_URL}/Archives/edgar/data/{cik}/{accession_no_dashes}/"
                f"{primary_docs[idx]}"
            )
            txt_url = (
                f"{self.BASE_URL}/cgi-bin/viewer?action=view&cik={cik}"
                f"&accession_number={accession_number}&xbrl_type=v"
            )

            return FilingMetadata(
                cik=cik,
                company_name=data.get("name", ""),
                form_type=form_types[idx],
                filing_date=filing_dates[idx],
                accession_number=accession_number,
                primary_doc_url=primary_doc_url,
                txt_url=txt_url,
                ticker=data.get("tickers", [None])[0] if data.get("tickers") else None,
            )

        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching filing: {e}")
            return None
        except (KeyError, IndexError) as e:
            logger.error(f"Error parsing filing data: {e}")
            return None


class MockSECClient(SECClient):
    """
    Mock SEC client for testing.

    Returns predefined filing data instead of making real API calls.
    """

    def __init__(self, mock_filings: Optional[List[FilingMetadata]] = None):
        """
        Initialize mock client.

        Args:
            mock_filings: List of FilingMetadata to return from searches
        """
        super().__init__(user_agent="mock-client")
        self.mock_filings = mock_filings or []

    def search_filings(
        self,
        start_date: str,
        end_date: str,
        form_types: Optional[List[str]] = None,
    ) -> List[FilingMetadata]:
        """Return mock filings filtered by date and form type."""
        if form_types is None:
            form_types = ['S-1', 'S-1/A', 'F-1', 'F-1/A']

        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        filtered = [
            f
            for f in self.mock_filings
            if f.form_type in form_types
            and start <= datetime.fromisoformat(f.filing_date) <= end
        ]

        logger.info(f"Mock search returned {len(filtered)} filings")
        return filtered

    def get_filing_by_accession(
        self, cik: str, accession_number: str
    ) -> Optional[FilingMetadata]:
        """Return mock filing by accession number."""
        for filing in self.mock_filings:
            if filing.cik == cik and filing.accession_number == accession_number:
                return filing
        return None
