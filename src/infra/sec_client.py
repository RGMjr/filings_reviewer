"""
SEC EDGAR client for querying filings.

Provides a simple abstraction over the SEC EDGAR API for discovering and fetching filing metadata.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from src.infra.exceptions import SECDataError, SECRateLimitError
from src.infra.http_client import HTTPClient, RequestsHTTPClient
from src.infra.validation import (
    ValidationError,
    extract_sec_accession_token,
    validate_date_range,
    validate_sic_code,
)

logger = logging.getLogger(__name__)


@dataclass
class SECClientMetrics:
    """Thread-safe metrics collection for SEC client requests.

    Attributes:
        requests_total: Total number of requests attempted
        requests_success: Number of successful requests
        requests_failed: Number of failed requests
        requests_timeout: Number of timeout failures
        total_elapsed_seconds: Total time spent on all requests
        _lock: Thread lock for safe concurrent access
    """

    requests_total: int = 0
    requests_success: int = 0
    requests_failed: int = 0
    requests_timeout: int = 0
    total_elapsed_seconds: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self) -> None:
        """Record that a request was attempted."""
        with self._lock:
            self.requests_total += 1

    def record_success(self, elapsed_seconds: float) -> None:
        """Record a successful request.

        Args:
            elapsed_seconds: Time taken for request
        """
        with self._lock:
            self.requests_success += 1
            self.total_elapsed_seconds += elapsed_seconds

    def record_failure(self, elapsed_seconds: float = 0.0) -> None:
        """Record a failed request.

        Args:
            elapsed_seconds: Time taken before failure
        """
        with self._lock:
            self.requests_failed += 1
            self.total_elapsed_seconds += elapsed_seconds

    def record_timeout(self, elapsed_seconds: float = 0.0) -> None:
        """Record a timeout failure.

        Args:
            elapsed_seconds: Time taken before timeout
        """
        with self._lock:
            self.requests_timeout += 1
            self.requests_failed += 1
            self.total_elapsed_seconds += elapsed_seconds

    def get_summary(self) -> dict:
        """Get metrics summary.

        Returns:
            Dictionary with metrics:
            - requests_total: Total requests
            - requests_success: Successful requests
            - requests_failed: Failed requests (including timeouts)
            - requests_timeout: Timeout failures
            - avg_elapsed_seconds: Average request time
            - success_rate: Percentage of successful requests
        """
        with self._lock:
            avg_elapsed = (
                self.total_elapsed_seconds / self.requests_total if self.requests_total > 0 else 0.0
            )
            success_rate = (
                (self.requests_success / self.requests_total * 100)
                if self.requests_total > 0
                else 0.0
            )

            return {
                "requests_total": self.requests_total,
                "requests_success": self.requests_success,
                "requests_failed": self.requests_failed,
                "requests_timeout": self.requests_timeout,
                "avg_elapsed_seconds": round(avg_elapsed, 3),
                "success_rate": round(success_rate, 1),
            }


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
    txt_url: str | None = None
    ticker: str | None = None


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

    def __init__(
        self,
        user_agent: str = "filings-reviewer info@example.com",
        http_client: HTTPClient | None = None,
        metrics: SECClientMetrics | None = None,
        image_cache_dir: str | Path | None = None,
        db_adapter=None,
    ):
        """
        Initialize SEC client.

        Args:
            user_agent: User agent string for SEC requests.
                MUST include company name and contact email per SEC policy.
            http_client: Optional HTTP client implementation. If None, creates
                RequestsHTTPClient with the provided user_agent. Allows injecting
                mock clients for testing.
            metrics: Optional metrics collector for tracking request statistics.
                If None, metrics collection is disabled.
            image_cache_dir: Optional directory for caching downloaded images.
                Structure: {cache_dir}/{cik}/{accession_no_dashes}/{filename}
                If None, images are not cached (fetched fresh each time).
            db_adapter: Optional DatabaseAdapter for PostgreSQL-backed image caching.
                Checked before disk cache; populated on fetch miss. Persists across
                Render redeploys. If None, only disk caching is used.
        """
        self.user_agent = user_agent

        # Use provided client or create default RequestsHTTPClient
        if http_client is None:
            self._http_client = RequestsHTTPClient(user_agent=user_agent)
        else:
            self._http_client = http_client

        # Optional metrics collection
        self._metrics = metrics

        # Optional image caching
        self._image_cache_dir: Path | None = None
        if image_cache_dir is not None:
            self._image_cache_dir = Path(image_cache_dir)

        # Optional PostgreSQL-backed image cache
        self._db_adapter = db_adapter

        # Keep session for backward compatibility with existing code
        # TODO: Remove once all code migrated to http_client
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _make_request(self, url: str, params: dict | None = None, max_retries: int = 3) -> dict:
        """
        Make a rate-limited request to SEC with retry logic.

        Implements exponential backoff for transient failures:
        - Retry on 5xx errors and timeouts
        - Skip retry on 4xx errors (client errors)
        - Backoff delays: 1s, 2s, 4s (max 3 retries)

        Args:
            url: URL to request
            params: Query parameters
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            JSON response as dict

        Raises:
            SECRateLimitError: If 429 rate limit exceeded
            SECDataError: If response is malformed JSON
            requests.HTTPError: If request fails after retries
            TimeoutError: If request times out after retries
        """
        import json as json_module

        for attempt in range(max_retries + 1):
            request_start_time = time.time()

            try:
                self._rate_limit()

                logger.debug(f"Requesting: {url} (attempt {attempt + 1}/{max_retries + 1})")

                # Record request attempt
                if self._metrics:
                    self._metrics.record_request()

                # Use HTTP client for request
                http_response = self._http_client.get(url, timeout=10.0)

                # Log timing
                logger.debug(f"Request completed in {http_response.elapsed_seconds:.3f}s")

                # Parse JSON response
                try:
                    data = json_module.loads(http_response.content)

                    # Record success
                    if self._metrics:
                        self._metrics.record_success(http_response.elapsed_seconds)

                    return data

                except json_module.JSONDecodeError as e:
                    # Invalid JSON is a non-retryable error
                    elapsed = time.time() - request_start_time
                    if self._metrics:
                        self._metrics.record_failure(elapsed)

                    preview = http_response.content[:200].decode("utf-8", errors="replace")
                    raise SECDataError(
                        f"Invalid JSON response from {url}: {e}", url=url, response_preview=preview
                    ) from e

            except requests.HTTPError as e:
                elapsed = time.time() - request_start_time
                status_code = e.response.status_code if hasattr(e, "response") else None

                # Record failure for all HTTP errors
                if self._metrics:
                    self._metrics.record_failure(elapsed)

                # Handle rate limiting (429)
                if status_code == 429:
                    logger.warning(f"Rate limit exceeded for {url}")
                    raise SECRateLimitError(f"Rate limit exceeded: {url}") from e

                # 4xx errors (client errors) - don't retry
                if status_code and 400 <= status_code < 500:
                    logger.debug(f"Client error {status_code} for {url} - not retrying")
                    raise

                # 5xx errors (server errors) - retry with backoff
                if status_code and status_code >= 500:
                    if attempt < max_retries:
                        backoff_delay = 2**attempt  # 1s, 2s, 4s
                        logger.warning(
                            f"Server error {status_code} for {url}. "
                            f"Retrying in {backoff_delay}s (attempt {attempt + 1}/{max_retries + 1})"
                        )
                        time.sleep(backoff_delay)
                        continue
                    else:
                        logger.error(f"Server error {status_code} for {url} - max retries exceeded")
                        raise

                # Unknown status - don't retry
                raise

            except TimeoutError:
                elapsed = time.time() - request_start_time

                # Record timeout
                if self._metrics:
                    self._metrics.record_timeout(elapsed)

                if attempt < max_retries:
                    backoff_delay = 2**attempt
                    logger.warning(
                        f"Timeout for {url}. Retrying in {backoff_delay}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(backoff_delay)
                    continue
                else:
                    logger.error(f"Timeout for {url} - max retries exceeded")
                    raise

        # Should never reach here
        raise RuntimeError(f"Unexpected end of retry loop for {url}")

    def search_filings(
        self,
        start_date: str,
        end_date: str,
        form_types: list[str] | None = None,
    ) -> list[FilingMetadata]:
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

        # Validate date range at entry point
        try:
            start, end = validate_date_range(start_date, end_date)
        except ValidationError as e:
            raise ValueError(str(e)) from e

        logger.info(f"Searching for filings: {start_date} to {end_date}, form_types={form_types}")

        filings = []
        current_date = start

        while current_date <= end:
            try:
                daily_filings = self._get_daily_filings(current_date, form_types)
                filings.extend(daily_filings)
                logger.info(f"Found {len(daily_filings)} filings on {current_date.date()}")
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

    def _get_daily_filings(self, date: datetime, form_types: list[str]) -> list[FilingMetadata]:
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
            f"{self.BASE_URL}/Archives/edgar/daily-index/{year}/QTR{quarter}/master.{date_str}.idx"
        )

        # Fetch and parse index file
        self._rate_limit()
        http_response = self._http_client.get(url, timeout=10.0)

        # Decode bytes to text
        response_text = http_response.content.decode("utf-8", errors="replace")

        return self._parse_master_index(response_text, form_types)

    def _parse_master_index(self, index_text: str, form_types: list[str]) -> list[FilingMetadata]:
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
            primary_doc_url = f"{self.BASE_URL}/Archives/edgar/data/{cik}/{accession_no_dashes}/"

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

    def resolve_primary_document_url(self, cik: str, accession_number: str) -> str | None:
        """
        Resolve the primary HTML document URL for a filing by fetching its index.

        Args:
            cik: SEC Central Index Key
            accession_number: SEC accession number (with dashes)

        Returns:
            Full URL to primary HTML document, or None if not found
        """
        bare = extract_sec_accession_token(accession_number)
        if bare is None:
            logger.warning(
                f"resolve_primary_document_url: no SEC accession token in "
                f"{accession_number!r}; cannot build EDGAR URL"
            )
            return None
        accession_no_dashes = bare.replace("-", "")
        index_url = f"{self.BASE_URL}/Archives/edgar/data/{cik}/{accession_no_dashes}/index.json"

        try:
            # Use _make_request for JSON with retry logic
            data = self._make_request(index_url)
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

            # IMPORTANT: Filter out exhibit files FIRST before pattern matching
            # Exhibit files often contain form patterns (e.g., "exhibit103s-1.htm")
            # which would incorrectly match before the actual S-1 document.
            # Match "ex" followed by a digit anywhere in the name to catch patterns
            # like "fs12019a1ex1-1_hennessy.htm" where "ex" is not at the start.
            _exhibit_re = re.compile(r"ex\d", re.IGNORECASE)
            non_exhibit_files = [
                item
                for item in htm_files
                if "exhibit" not in item["name"].lower()
                and "filingfee" not in item["name"].lower()
                and not _exhibit_re.search(item["name"])
            ]

            # Use non-exhibit files for pattern matching if available
            files_for_pattern_match = non_exhibit_files if non_exhibit_files else htm_files

            # Find primary doc (matches form type pattern)
            # Try multiple pattern matching strategies in order of preference

            # Strategy 1: Look for explicit form type patterns in non-exhibit files
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
                "mainbody",  # Common main document naming
                "prospectus",  # Prospectus filings
                "registration",  # Registration statements
            ]

            # Iterate patterns first (highest priority wins), then files.
            # This ensures "s-1" always beats "prospectus" regardless of
            # alphabetical file ordering in the SEC index.
            for pattern in form_patterns:
                for item in files_for_pattern_match:
                    if pattern in item["name"].lower():
                        primary_doc = item["name"]
                        logger.debug(f"Found primary doc by pattern '{pattern}': {primary_doc}")
                        return (
                            f"{self.BASE_URL}/Archives/edgar/data/{cik}/"
                            f"{accession_no_dashes}/{primary_doc}"
                        )

            # Strategy 2: Use largest non-exhibit HTML file (likely the main document)
            files_to_consider = non_exhibit_files if non_exhibit_files else htm_files

            # Get file with largest size
            largest_file = max(files_to_consider, key=lambda x: int(x.get("size", 0) or 0))
            primary_doc = largest_file["name"]

            logger.debug(
                f"Using largest file as primary doc: {primary_doc} "
                f"({largest_file.get('size', 0)} bytes)"
            )

            return f"{self.BASE_URL}/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"

        except Exception as e:
            logger.error(f"Error resolving primary doc for {cik}/{accession_number}: {e}")
            return None

    def get_company_info(self, cik: str) -> dict | None:
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

            # Validate and normalize SIC code if present
            raw_sic = data.get("sic", "")
            sic_code = ""
            if raw_sic:
                try:
                    sic_code = validate_sic_code(str(raw_sic))
                except ValidationError as e:
                    logger.warning(
                        f"Invalid SIC code '{raw_sic}' for CIK {cik}: {e}. Using raw value."
                    )
                    sic_code = str(raw_sic)

            return {
                "cik": cik_padded,
                "name": data.get("name", ""),
                "sic": sic_code,
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

    def fetch_filing_text_sample(self, url: str, max_chars: int = 10000) -> str | None:
        """
        Fetch the first max_chars characters of a filing document for classification.

        Used to detect SPAC language ("blank check company", etc.) in the filing text
        when name and SIC checks are inconclusive.

        Args:
            url: URL to the filing document (primary_doc_url or txt_url)
            max_chars: Maximum characters to return (default 10000)

        Returns:
            First max_chars characters of the document text, or None on error.
        """
        try:
            self._rate_limit()
            http_response = self._http_client.get(url, timeout=15.0)
            text = http_response.content.decode("utf-8", errors="replace")
            return text[:max_chars]
        except Exception as e:
            logger.warning(f"Failed to fetch filing text sample from {url}: {e}")
            return None

    def get_filing_by_accession(self, cik: str, accession_number: str) -> FilingMetadata | None:
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
                logger.warning(f"Accession number {accession_number} not found for CIK {cik}")
                return None

            # Extract filing metadata
            form_types = recent.get("form", [])
            filing_dates = recent.get("filingDate", [])
            primary_docs = recent.get("primaryDocument", [])

            # Construct URLs
            bare = extract_sec_accession_token(accession_number)
            if bare is None:
                logger.warning(
                    f"get_filing_by_accession: no SEC accession token in "
                    f"{accession_number!r}; cannot build EDGAR URL"
                )
                return None
            accession_no_dashes = bare.replace("-", "")
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

    def get_latest_registration_filing(
        self,
        cik: str,
        form_types: list[str] | None = None,
    ) -> FilingMetadata | None:
        """
        Get the most recent S-1/S-1/A or F-1/F-1/A filing for a company.

        This is useful for finding the "final" registration statement,
        which is typically the last S-1/A filed before IPO.

        Note: For older IPOs (>2 years), the S-1 may be in archived filing
        files rather than the "recent" filings array. This method searches
        both recent and archived filings.

        Args:
            cik: SEC Central Index Key
            form_types: Optional list of form types to search for.
                        Defaults to ["S-1", "S-1/A", "F-1", "F-1/A"]

        Returns:
            FilingMetadata for the most recent matching filing, or None
        """
        if form_types is None:
            form_types = ["S-1", "S-1/A", "F-1", "F-1/A"]

        # Normalize CIK to 10 digits with leading zeros
        cik_padded = cik.zfill(10)

        try:
            # Get company submissions data
            url = self.SUBMISSIONS_URL.format(cik=cik_padded)
            data = self._make_request(url)

            company_name = data.get("name", "")
            ticker = data.get("tickers", [None])[0] if data.get("tickers") else None

            # First, search recent filings
            recent = data.get("filings", {}).get("recent", {})
            result = self._search_filings_array(
                recent, form_types, cik_padded, company_name, ticker
            )
            if result:
                return result

            # If not found in recent, search archived filing files
            # These contain older filings (typically >2 years old)
            archived_files = data.get("filings", {}).get("files", [])
            for file_info in archived_files:
                file_name = file_info.get("name", "")
                if not file_name:
                    continue

                # Fetch the archived filing file
                archive_url = f"https://data.sec.gov/submissions/{file_name}"
                logger.debug(f"Searching archived filings: {file_name}")

                try:
                    archived_data = self._make_request(archive_url)
                    result = self._search_filings_array(
                        archived_data, form_types, cik_padded, company_name, ticker
                    )
                    if result:
                        return result
                except Exception as e:
                    logger.warning(f"Error fetching archived file {file_name}: {e}")
                    continue

            logger.warning(f"No {form_types} filings found for CIK {cik}")
            return None

        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching filings for CIK {cik}: {e}")
            return None
        except (KeyError, IndexError) as e:
            logger.error(f"Error parsing filing data for CIK {cik}: {e}")
            return None

    def _get_image_cache_path(self, cik: str, accession_number: str, filename: str) -> Path | None:
        """Get cache path for an image, or None if caching disabled.

        Args:
            cik: SEC Central Index Key (raw, will be stripped of leading zeros)
            accession_number: SEC accession number (with dashes)
            filename: Image filename

        Returns:
            Path to cached image file, or None if caching is disabled
        """
        if self._image_cache_dir is None:
            return None

        bare = extract_sec_accession_token(accession_number)
        if bare is None:
            logger.warning(
                f"_get_image_cache_path: no SEC accession token in "
                f"{accession_number!r}; cache path unavailable"
            )
            return None
        cik_stripped = cik.lstrip("0") or "0"
        accession_no_dashes = bare.replace("-", "")

        return self._image_cache_dir / cik_stripped / accession_no_dashes / filename

    def get_image_cache_path(self, cik: str, accession_number: str, filename: str) -> Path:
        """Return the cache path for an image (public accessor).

        Args:
            cik: SEC Central Index Key (raw, will be stripped of leading zeros)
            accession_number: SEC accession number (with dashes)
            filename: Image filename

        Returns:
            Path to the cached image file

        Raises:
            ValueError: If image caching was not configured (image_cache_dir is None)
        """
        path = self._get_image_cache_path(cik, accession_number, filename)
        if path is None:
            raise ValueError(
                "get_image_cache_path called but image_cache_dir was not set on this SECClient"
            )
        return path

    def _read_cached_image(self, cache_path: Path) -> bytes | None:
        """Read image from cache if it exists.

        Args:
            cache_path: Path to cached image file

        Returns:
            Image bytes if cached, None otherwise
        """
        if cache_path.exists():
            try:
                image_bytes = cache_path.read_bytes()
                logger.debug(f"Cache hit: {cache_path} ({len(image_bytes)} bytes)")
                return image_bytes
            except OSError as e:
                logger.warning(f"Failed to read cached image {cache_path}: {e}")
        return None

    def _write_cached_image(self, cache_path: Path, image_bytes: bytes) -> None:
        """Write image to cache.

        Args:
            cache_path: Path to cache file
            image_bytes: Image data to cache
        """
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(image_bytes)
            logger.debug(f"Cached image: {cache_path} ({len(image_bytes)} bytes)")
        except OSError as e:
            logger.warning(f"Failed to cache image {cache_path}: {e}")

    def fetch_image(
        self,
        cik: str,
        accession_number: str,
        filename: str,
        *,
        max_size_bytes: int = 10 * 1024 * 1024,  # 10MB default limit
    ) -> bytes | None:
        """
        Fetch an image file from SEC EDGAR, with optional caching.

        Args:
            cik: SEC Central Index Key (will NOT be zero-padded - SEC URLs use raw CIK)
            accession_number: SEC accession number (with dashes, e.g., "0001234567-24-000001")
            filename: Image filename from the filing (e.g., "chart1.jpg")
            max_size_bytes: Maximum allowed image size (default 10MB)

        Returns:
            Raw image bytes, or None if fetch failed (404, network error, too large)

        Note:
            - If image_cache_dir was set, checks cache before fetching from SEC
            - Respects existing rate limiting (100ms minimum between requests)
            - Validates Content-Type is an image type
            - Logs warnings for failures (does not raise exceptions)
        """
        # Compute canonical key components used by both DB and disk caches.
        # extract_sec_accession_token strips synthetic ``presentation:`` /
        # ``transcript:`` prefixes so the resulting EDGAR URL is well-formed
        # for filings ingested via the presentation/transcript path
        # (legacy-104).
        bare = extract_sec_accession_token(accession_number)
        if bare is None:
            logger.warning(
                f"fetch_image: no SEC accession token in {accession_number!r}; "
                f"cannot build EDGAR URL"
            )
            return None
        cik_stripped = cik.lstrip("0") or "0"
        accession_no_dashes = bare.replace("-", "")

        # Check DB cache first (persists across redeploys)
        if self._db_adapter is not None:
            try:
                cached_db = self._db_adapter.get_cached_image(
                    cik_stripped, accession_no_dashes, filename
                )
                if cached_db is not None:
                    logger.debug(f"DB cache hit: {cik_stripped}/{accession_no_dashes}/{filename}")
                    return cached_db["image_data"]
            except Exception as e:
                logger.warning(f"DB cache lookup failed for {filename}: {e}")

        # Check disk cache (local dev speed)
        cache_path = self._get_image_cache_path(cik, accession_number, filename)
        if cache_path is not None:
            cached = self._read_cached_image(cache_path)
            if cached is not None:
                return cached

        url = f"{self.BASE_URL}/Archives/edgar/data/{cik_stripped}/{accession_no_dashes}/{filename}"

        try:
            self._rate_limit()

            logger.debug(f"Fetching image: {url}")

            # Record request attempt
            if self._metrics:
                self._metrics.record_request()

            # Use HTTP client for request
            http_response = self._http_client.get(url, timeout=30.0)

            # Record success timing
            if self._metrics:
                self._metrics.record_success(http_response.elapsed_seconds)

            # Validate Content-Type is an image
            content_type = http_response.headers.get("Content-Type", "").lower()
            if not content_type.startswith("image/"):
                logger.warning(f"Invalid Content-Type for image {filename}: {content_type}")
                return None

            # Check Content-Length before reading full response
            content_length = http_response.headers.get("Content-Length")
            if content_length:
                try:
                    size = int(content_length)
                    if size > max_size_bytes:
                        logger.warning(
                            f"Image {filename} exceeds size limit: {size} > {max_size_bytes} bytes"
                        )
                        return None
                except ValueError:
                    pass  # Invalid Content-Length header, proceed with download

            # Check actual content size
            image_bytes = http_response.content
            if len(image_bytes) > max_size_bytes:
                logger.warning(
                    f"Image {filename} exceeds size limit: "
                    f"{len(image_bytes)} > {max_size_bytes} bytes"
                )
                return None

            logger.debug(
                f"Fetched image {filename}: {len(image_bytes)} bytes, "
                f"{http_response.elapsed_seconds:.3f}s"
            )

            # Write to DB cache (persists across redeploys)
            if self._db_adapter is not None:
                try:
                    self._db_adapter.store_cached_image(
                        cik_stripped,
                        accession_no_dashes,
                        filename,
                        image_bytes,
                        content_type,
                    )
                except Exception as e:
                    logger.warning(f"DB cache write failed for {filename}: {e}")

            # Write to disk cache (local dev speed)
            if cache_path is not None:
                self._write_cached_image(cache_path, image_bytes)

            return image_bytes

        except Exception as e:
            elapsed = 0.0
            if self._metrics:
                self._metrics.record_failure(elapsed)

            logger.warning(f"Failed to fetch image {filename} from {url}: {e}")
            return None

    def _search_filings_array(
        self,
        filings_data: dict,
        form_types: list[str],
        cik_padded: str,
        company_name: str,
        ticker: str | None,
    ) -> FilingMetadata | None:
        """Search a filings array for matching form types.

        Helper method for get_latest_registration_filing.
        """
        forms = filings_data.get("form", [])
        accession_numbers = filings_data.get("accessionNumber", [])
        filing_dates = filings_data.get("filingDate", [])
        primary_docs = filings_data.get("primaryDocument", [])

        # Find the first (most recent) matching filing
        for i, form in enumerate(forms):
            if form in form_types:
                accession_number = accession_numbers[i]
                bare = extract_sec_accession_token(accession_number)
                if bare is None:
                    logger.warning(
                        f"_search_filings_array: no SEC accession token in "
                        f"{accession_number!r}; skipping"
                    )
                    continue
                accession_no_dashes = bare.replace("-", "")
                primary_doc = primary_docs[i] if i < len(primary_docs) else ""

                primary_doc_url = (
                    f"{self.BASE_URL}/Archives/edgar/data/"
                    f"{cik_padded}/{accession_no_dashes}/{primary_doc}"
                )
                txt_url = (
                    f"{self.BASE_URL}/cgi-bin/viewer?action=view&cik={cik_padded}"
                    f"&accession_number={accession_number}&xbrl_type=v"
                )

                logger.info(
                    f"Found latest {form} for {company_name}: "
                    f"{accession_number} ({filing_dates[i]})"
                )

                return FilingMetadata(
                    cik=cik_padded,
                    company_name=company_name,
                    form_type=form,
                    filing_date=filing_dates[i],
                    accession_number=accession_number,
                    primary_doc_url=primary_doc_url,
                    txt_url=txt_url,
                    ticker=ticker,
                )

        return None


class MockSECClient(SECClient):
    """
    Mock SEC client for testing.

    Returns predefined filing data instead of making real API calls.
    """

    def __init__(
        self,
        mock_filings: list[FilingMetadata] | None = None,
        mock_company_info: dict[str, dict] | None = None,
        mock_filing_texts: dict[str, str] | None = None,
    ):
        """
        Initialize mock client.

        Args:
            mock_filings: List of FilingMetadata to return from searches
            mock_company_info: Dict mapping CIK -> company info dict (including 'sic')
            mock_filing_texts: Dict mapping URL -> text content for fetch_filing_text_sample
        """
        super().__init__(user_agent="mock-client")
        self.mock_filings = mock_filings or []
        self.mock_company_info = mock_company_info or {}
        self.mock_filing_texts = mock_filing_texts or {}

    def search_filings(
        self,
        start_date: str,
        end_date: str,
        form_types: list[str] | None = None,
    ) -> list[FilingMetadata]:
        """Return mock filings filtered by date and form type."""
        if form_types is None:
            form_types = ["S-1", "S-1/A", "F-1", "F-1/A"]

        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        filtered = [
            f
            for f in self.mock_filings
            if f.form_type in form_types and start <= datetime.fromisoformat(f.filing_date) <= end
        ]

        logger.info(f"Mock search returned {len(filtered)} filings")
        return filtered

    def get_company_info(self, cik: str) -> dict | None:
        """Return mock company info for the given CIK, or None if not configured."""
        return self.mock_company_info.get(cik)

    def fetch_filing_text_sample(self, url: str, max_chars: int = 10000) -> str | None:
        """Return mock filing text for the given URL, or None if not configured."""
        text = self.mock_filing_texts.get(url)
        return text[:max_chars] if text else None

    def get_filing_by_accession(self, cik: str, accession_number: str) -> FilingMetadata | None:
        """Return mock filing by accession number."""
        for filing in self.mock_filings:
            if filing.cik == cik and filing.accession_number == accession_number:
                return filing
        return None
