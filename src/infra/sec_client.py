"""
SEC EDGAR client for querying filings.

Provides a simple abstraction over the SEC EDGAR API for discovering and fetching filing metadata.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

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
        Search for filings in a date range using SEC daily index files.

        This implementation parses SEC's daily master index files to discover filings.
        See: https://www.sec.gov/Archives/edgar/daily-index/

        Args:
            start_date: Start date (ISO format: YYYY-MM-DD)
            end_date: End date (ISO format: YYYY-MM-DD)
            form_types: List of form types to include (e.g., ['S-1', 'F-1']).
                If None, defaults to ['S-1', 'S-1/A', 'F-1', 'F-1/A']

        Returns:
            List of FilingMetadata objects

        Note:
            This queries daily index files which can be slow for large date ranges.
            For production, consider caching index files or using bulk downloads.
        """
        if form_types is None:
            form_types = ["S-1", "S-1/A", "F-1", "F-1/A"]

        logger.info(
            f"Searching for filings: {start_date} to {end_date}, "
            f"form_types={form_types}"
        )

        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        filings = []
        current_date = start

        while current_date <= end:
            try:
                daily_filings = self._get_daily_filings(current_date, form_types)
                filings.extend(daily_filings)
                logger.info(
                    f"Found {len(daily_filings)} filings on {current_date.date()}"
                )
            except requests.HTTPError as e:
                if e.response.status_code == 404:
                    logger.debug(f"No index file for {current_date.date()}")
                else:
                    logger.warning(f"Error fetching {current_date.date()}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error for {current_date.date()}: {e}")

            # Move to next day
            from datetime import timedelta

            current_date += timedelta(days=1)

        logger.info(f"Total filings found: {len(filings)}")
        return filings

    def _get_daily_filings(
        self, date: datetime, form_types: List[str]
    ) -> List[FilingMetadata]:
        """
        Get filings from a single day's master index file.

        Args:
            date: Date to fetch
            form_types: List of form types to include

        Returns:
            List of FilingMetadata for that day
        """
        # Construct URL to daily master index
        # Format: https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/master.20240115.idx
        quarter = (date.month - 1) // 3 + 1
        year = date.year
        date_str = date.strftime("%Y%m%d")

        url = (
            f"{self.BASE_URL}/Archives/edgar/daily-index/"
            f"{year}/QTR{quarter}/master.{date_str}.idx"
        )

        # Fetch and parse index file
        self._rate_limit()
        response = self.session.get(url)
        response.raise_for_status()

        return self._parse_master_index(response.text, form_types)

    def _parse_master_index(
        self, index_text: str, form_types: List[str]
    ) -> List[FilingMetadata]:
        """
        Parse SEC master index file format.

        Format:
        CIK|Company Name|Form Type|Date Filed|Filename

        Args:
            index_text: Raw index file text
            form_types: List of form types to include

        Returns:
            List of FilingMetadata objects
        """
        filings = []

        # Skip header lines (first ~10 lines are header)
        lines = index_text.strip().split("\n")
        data_start = 0
        for i, line in enumerate(lines):
            if line.startswith("---"):
                data_start = i + 1
                break

        # Parse data lines
        for line in lines[data_start:]:
            if not line.strip():
                continue

            parts = line.split("|")
            if len(parts) < 5:
                continue

            cik, company_name, form_type, filing_date, filename = parts[:5]

            # Filter by form type
            if form_type not in form_types:
                continue

            # Construct URLs
            cik = cik.strip()
            accession_number = self._extract_accession_from_filename(filename)

            # The raw text file URL from the index
            txt_url = f"{self.BASE_URL}/{filename.strip()}"

            # Primary doc URL needs to be resolved from the filing's index
            # We store a placeholder directory URL that FilingFetcher will resolve
            accession_no_dashes = accession_number.replace("-", "")
            primary_doc_url = (
                f"{self.BASE_URL}/Archives/edgar/data/{cik}/{accession_no_dashes}/"
            )

            filings.append(
                FilingMetadata(
                    cik=cik.zfill(10),  # Pad CIK to 10 digits
                    company_name=company_name.strip(),
                    form_type=form_type.strip(),
                    filing_date=filing_date.strip(),
                    accession_number=accession_number,
                    primary_doc_url=primary_doc_url,
                    txt_url=txt_url,
                    ticker=None,  # Not available in index files
                )
            )

        return filings

    def _extract_accession_from_filename(self, filename: str) -> str:
        """
        Extract accession number from filename.

        Filename format: edgar/data/1234567/0001193125-19-163007.txt
        Accession is the 0001193125-19-163007 part (filename without extension)

        Args:
            filename: Filename from index

        Returns:
            Accession number
        """
        parts = filename.strip().split("/")
        if len(parts) >= 4:
            # Last part is the filename with extension (e.g., "0001193125-19-163007.txt")
            filename_with_ext = parts[-1]
            # Remove extension to get accession number
            accession = filename_with_ext.rsplit(".", 1)[0]
            return accession
        return ""

    def resolve_primary_document_url(
        self, cik: str, accession_number: str
    ) -> Optional[str]:
        """
        Resolve the primary HTML document URL for a filing by fetching its index.

        Args:
            cik: SEC Central Index Key
            accession_number: SEC accession number (with dashes)

        Returns:
            Full URL to primary HTML document, or None if not found
        """
        accession_no_dashes = accession_number.replace("-", "")
        index_url = (
            f"{self.BASE_URL}/Archives/edgar/data/{cik}/"
            f"{accession_no_dashes}/index.json"
        )

        try:
            self._rate_limit()
            response = self.session.get(index_url)
            response.raise_for_status()

            data = response.json()
            directory = data.get("directory", {})
            items = directory.get("item", [])

            # Look for primary HTML document
            htm_files = [
                item
                for item in items
                if item["name"].endswith((".htm", ".html"))
                and not item["name"].startswith("R")  # Exclude XBRL
            ]

            if not htm_files:
                logger.warning(f"No HTML files found for {cik}/{accession_number}")
                return None

            # Find primary doc (matches form type pattern)
            # Try multiple pattern matching strategies in order of preference

            # Strategy 1: Look for explicit form type patterns
            form_patterns = [
                "s-1",
                "f-1",  # Standard patterns with dashes
                "ds1",
                "df1",  # Document patterns
                "forms1",
                "formf1",  # Form prefix patterns
                "form_s-1",
                "form_f-1",  # Form with underscore
                "ss1",
                "ff1",  # Compact patterns (no separator)
                "s1a",
                "f1a",  # Amendment patterns
                "filing",  # Generic filing
                "mainbody",  # Common main document naming
                "prospectus",  # Prospectus filings
                "registration",  # Registration statements
            ]

            for item in htm_files:
                name = item["name"].lower()
                if any(pattern in name for pattern in form_patterns):
                    primary_doc = item["name"]
                    logger.debug(f"Found primary doc by pattern: {primary_doc}")
                    return (
                        f"{self.BASE_URL}/Archives/edgar/data/{cik}/"
                        f"{accession_no_dashes}/{primary_doc}"
                    )

            # Strategy 2: Use largest HTML file (likely the main document)
            # Exclude exhibit files (typically have 'exhibit' or 'ex' in name)
            non_exhibit_files = [
                item
                for item in htm_files
                if "exhibit" not in item["name"].lower()
                and not item["name"].lower().startswith("ex")
            ]

            files_to_consider = non_exhibit_files if non_exhibit_files else htm_files

            # Get file with largest size
            largest_file = max(files_to_consider, key=lambda x: x.get("size", 0))
            primary_doc = largest_file["name"]

            logger.debug(
                f"Using largest file as primary doc: {primary_doc} "
                f"({largest_file.get('size', 0)} bytes)"
            )

            return (
                f"{self.BASE_URL}/Archives/edgar/data/{cik}/"
                f"{accession_no_dashes}/{primary_doc}"
            )

        except Exception as e:
            logger.error(
                f"Error resolving primary doc for {cik}/{accession_number}: {e}"
            )
            return None

    def get_company_info(self, cik: str) -> Optional[dict]:
        """
        Get company information including SIC code from SEC submissions API.

        Args:
            cik: SEC Central Index Key (can be any length, will be padded)

        Returns:
            Dictionary with company info:
            {
                'cik': str,
                'name': str,
                'sic': str (4-digit code),
                'sic_description': str,
                'tickers': List[str],
                'ein': str (employer identification number),
                'state_of_incorporation': str,
            }
            Returns None if company not found or error occurs.
        """
        # Normalize CIK to 10 digits with leading zeros
        cik_padded = cik.zfill(10)

        try:
            url = self.SUBMISSIONS_URL.format(cik=cik_padded)
            data = self._make_request(url)

            return {
                "cik": cik_padded,
                "name": data.get("name", ""),
                "sic": data.get("sic", ""),
                "sic_description": data.get("sicDescription", ""),
                "tickers": data.get("tickers", []),
                "ein": data.get("ein", ""),
                "state_of_incorporation": data.get("stateOfIncorporation", ""),
            }

        except requests.HTTPError as e:
            if e.response.status_code == 404:
                logger.debug(f"Company not found for CIK {cik}")
            else:
                logger.error(f"HTTP error fetching company info for CIK {cik}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching company info for CIK {cik}: {e}")
            return None

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
            form_types = ["S-1", "S-1/A", "F-1", "F-1/A"]

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
