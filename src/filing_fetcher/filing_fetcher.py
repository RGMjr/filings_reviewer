"""
FilingFetcher: Downloads and caches SEC filing HTML/TXT documents locally.

This component:
1. Downloads HTML and TXT filings from SEC EDGAR
2. Stores them locally in organized directory structure
3. Updates database to track fetched filings
4. Supports batch processing with rate limiting
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import requests

from src.infra.sec_client import FilingMetadata

logger = logging.getLogger(__name__)


@dataclass
class FilingContent:
    """
    Represents downloaded filing content.

    Attributes:
        cik: SEC Central Index Key
        accession_number: SEC accession number
        html_path: Local path to HTML filing
        txt_path: Local path to complete text filing
        fetched_at: Timestamp when fetched
    """

    cik: str
    accession_number: str
    html_path: str
    txt_path: Optional[str] = None
    fetched_at: Optional[datetime] = None


class FilingFetcher:
    """
    Downloads and caches SEC filings locally.

    Organizes filings in directory structure:
        data/filings/{cik}/{accession_number}/
            - primary.htm (main HTML document)
            - complete.txt (complete text filing)
    """

    # Rate limiting: SEC requests max 10 requests per second
    MIN_REQUEST_INTERVAL = 0.11  # slightly over 100ms to be safe

    def __init__(
        self,
        storage_root: str = "data/filings",
        user_agent: str = "CMASB Filings Analyzer rgmarkey@gmail.com",
        db=None,
        sec_client=None,
    ):
        """
        Initialize FilingFetcher.

        Args:
            storage_root: Root directory for storing filings
            user_agent: User agent for SEC requests (must include contact email)
            db: DatabaseAdapter instance (optional, for tracking fetched filings)
            sec_client: SECClient instance (optional, for resolving primary doc URLs)
        """
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)

        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

        self.db = db
        self.sec_client = sec_client
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _get_storage_dir(self, cik: str, accession_number: str) -> Path:
        """
        Get storage directory for a filing.

        Args:
            cik: SEC Central Index Key
            accession_number: SEC accession number

        Returns:
            Path to storage directory

        Raises:
            ValueError: If CIK or accession number contains path traversal sequences
        """
        # Security: Validate inputs to prevent path traversal attacks
        if ".." in cik or "/" in cik or "\\" in cik:
            raise ValueError("Invalid CIK: contains path traversal characters")
        if (
            ".." in accession_number
            or "/" in accession_number.replace("-", "")
            or "\\" in accession_number
        ):
            raise ValueError(
                "Invalid accession number: contains path traversal characters"
            )

        # Additional validation: CIK should be numeric
        if not cik.isdigit():
            raise ValueError("Invalid CIK: must be numeric")

        # Remove dashes from accession number for directory name
        accession_clean = accession_number.replace("-", "")

        # Validate accession format (should be alphanumeric after removing dashes)
        if not accession_clean.replace("-", "").isalnum():
            raise ValueError("Invalid accession number: must be alphanumeric")

        return self.storage_root / cik / accession_clean

    def _validate_filing_content(
        self, html: str, cik: str, accession_number: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that HTML content is a real SEC filing, not an error page.

        Supports three filing formats:
        - SGML-wrapped filings (older, with <DOCUMENT> tag)
        - Modern pure HTML filings (2022+, without SGML wrapper)
        - iXBRL filings (2021+, XML+HTML with XBRL namespaces)

        Args:
            html: HTML content to validate
            cik: Expected CIK for additional validation
            accession_number: Expected accession number

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check 1: Minimum size - SEC filings are typically > 15KB
        # Lowered from 20KB to capture small legitimate filings (amendments, etc.)
        if len(html) < 15_000:
            return (
                False,
                f"Content too small ({len(html):,} bytes, expected > 15KB) - likely an error page",
            )

        # Check 2: Must NOT contain error indicators (check early to fail fast)
        error_markers = [
            "No rendered XBRL documents",
            "No documents were found",
            "404 Not Found",
            "Page Not Found",
            "Error processing request",
            "The requested URL was not found",
            "Access Denied",
            "Service Unavailable",
            "NoSuchKey",  # S3 error
            "<Error>",  # XML error response
        ]

        for marker in error_markers:
            if marker in html:
                return False, f"Error page detected: contains '{marker}'"

        # Check 3: Detect iXBRL format (XML-based HTML with XBRL namespaces)
        # iXBRL filings start with XML declaration and contain XBRL namespaces
        # These are inline XBRL documents adopted by SEC around 2021
        content_start = html[:3000].strip()  # Check first 3KB for performance

        if content_start.startswith("<?xml"):
            # This appears to be an iXBRL filing
            # Verify it contains XBRL namespace
            has_ixbrl_namespace = (
                'xmlns:ix="http://www.xbrl.org' in html[:5000]
                or "xmlns:ix='http://www.xbrl.org" in html[:5000]
            )

            if has_ixbrl_namespace:
                # Verify it's still HTML-based (not pure XML)
                if "<html" not in html[:5000].lower():
                    return False, "iXBRL file missing HTML structure"

                # Verify it has body content
                if "<body" not in html[:10000].lower():
                    return False, "iXBRL file missing body content"

                # iXBRL format validated - return success early
                logger.debug(
                    f"Detected iXBRL format for {cik}/{accession_number}"
                )
                return True, None

        # Check 4: Detect filing format (SGML vs modern HTML)
        has_document_tag = "<DOCUMENT>" in html
        has_html_structure = any(
            tag in html for tag in ["<!DOCTYPE", "<HTML>", "<html>"]
        )
        has_sgml_structure = "<TEXT>" in html

        is_sgml_format = has_document_tag and has_sgml_structure
        is_modern_html = has_html_structure and not has_document_tag

        # Must be one of the two supported formats
        if not (is_sgml_format or is_modern_html or has_document_tag):
            # Lenient: If it has <DOCUMENT> tag OR proper HTML structure, allow it
            if not (has_document_tag or has_html_structure):
                return (
                    False,
                    "Missing valid filing structure (neither SGML nor HTML format)",
                )

        # Check 5: Must contain SEC filing indicators
        # At least one of these should be present in a real filing
        sec_indicators = [
            "SECURITIES AND EXCHANGE COMMISSION",
            "Securities and Exchange Commission",
            "UNITED STATES SECURITIES AND EXCHANGE COMMISSION",
            "U.S. SECURITIES AND EXCHANGE COMMISSION",
            "FORM S-1",
            "FORM F-1",
            "REGISTRATION STATEMENT",
        ]

        has_sec_reference = any(indicator in html for indicator in sec_indicators)

        if not has_sec_reference:
            return False, "Missing SEC filing indicators - content may not be a filing"

        # Check 6: Additional validation for modern HTML format
        if is_modern_html:
            # Modern HTML filings should have more structured content
            html_lower = html.lower()

            # Should contain typical filing elements
            filing_elements = [
                "<title>",
                "<body",
                "<div",
                "<table",
            ]

            has_filing_elements = (
                sum(1 for elem in filing_elements if elem in html_lower) >= 2
            )

            if not has_filing_elements:
                return False, "Modern HTML filing missing expected structural elements"

        # All checks passed
        return True, None

    def fetch_filing(
        self, filing_metadata: FilingMetadata, fetch_txt: bool = True
    ) -> Optional[FilingContent]:
        """
        Download and cache a single filing.

        Args:
            filing_metadata: Filing metadata with URLs
            fetch_txt: Whether to also fetch complete text filing

        Returns:
            FilingContent if successful, None otherwise
        """
        cik = filing_metadata.cik
        accession_number = filing_metadata.accession_number

        logger.info(f"Fetching filing {cik}/{accession_number}")

        # Create storage directory
        storage_dir = self._get_storage_dir(cik, accession_number)
        storage_dir.mkdir(parents=True, exist_ok=True)

        html_path = storage_dir / "primary.htm"
        txt_path = storage_dir / "complete.txt"

        # Track resolved URL to persist to database
        resolved_url_for_db = None

        try:
            # Fetch HTML filing
            if not html_path.exists():
                # Resolve primary document URL if it's a directory URL
                primary_doc_url = filing_metadata.primary_doc_url
                if primary_doc_url.endswith("/") and self.sec_client:
                    logger.debug(
                        f"Resolving primary doc URL for {cik}/{accession_number}"
                    )
                    resolved_url = self.sec_client.resolve_primary_document_url(
                        cik, accession_number
                    )
                    if resolved_url:
                        primary_doc_url = resolved_url
                        resolved_url_for_db = resolved_url  # Save for database update
                    else:
                        raise ValueError("Could not resolve primary document URL")

                self._rate_limit()
                logger.debug(f"Downloading HTML: {primary_doc_url}")
                response = self.session.get(primary_doc_url)
                response.raise_for_status()

                # Validate content before saving
                is_valid, error_msg = self._validate_filing_content(
                    response.text, cik, accession_number
                )
                if not is_valid:
                    raise ValueError(f"Invalid filing content: {error_msg}")

                html_path.write_text(response.text, encoding="utf-8")
                logger.info(f"Saved HTML to {html_path}")
            else:
                logger.debug(f"HTML already cached: {html_path}")

            # Fetch TXT filing (if requested and URL available)
            # TXT files are optional - don't fail entire fetch if unavailable
            txt_path_str = None
            if fetch_txt and filing_metadata.txt_url:
                try:
                    if not txt_path.exists():
                        self._rate_limit()
                        logger.debug(f"Downloading TXT: {filing_metadata.txt_url}")
                        response = self.session.get(filing_metadata.txt_url)
                        response.raise_for_status()

                        txt_path.write_text(response.text, encoding="utf-8")
                        logger.info(f"Saved TXT to {txt_path}")
                        txt_path_str = str(txt_path)
                    else:
                        logger.debug(f"TXT already cached: {txt_path}")
                        txt_path_str = str(txt_path)
                except requests.HTTPError as e:
                    # TXT file not available (404) - this is OK, HTML is sufficient
                    logger.warning(
                        f"TXT file not available for {cik}/{accession_number}: {e}"
                    )
                except Exception as e:
                    # Other TXT errors - log but don't fail entire fetch
                    logger.warning(
                        f"Error fetching TXT for {cik}/{accession_number}: {e}"
                    )

            # Create FilingContent result
            content = FilingContent(
                cik=cik,
                accession_number=accession_number,
                html_path=str(html_path),
                txt_path=txt_path_str,
                fetched_at=datetime.now(),
            )

            # Update database if available
            if self.db:
                self._update_database(content, error=None, resolved_url=resolved_url_for_db)

            return content

        except requests.HTTPError as e:
            # HTTP errors (4xx, 5xx) - may be transient, retryable
            error_msg = f"HTTP error fetching {cik}/{accession_number}: {e}"
            logger.error(error_msg)

            if self.db:
                self._update_database_error(cik, accession_number, error_msg)

            return None

        except ValueError as e:
            # Validation errors - permanent, not retryable
            error_msg = f"Validation error for {cik}/{accession_number}: {e}"
            logger.error(error_msg)

            if self.db:
                self._update_database_error(cik, accession_number, error_msg)

            return None

        except requests.RequestException as e:
            # Other network errors (timeout, connection) - transient, retryable
            error_msg = f"Network error fetching {cik}/{accession_number}: {e}"
            logger.error(error_msg, exc_info=True)

            if self.db:
                self._update_database_error(cik, accession_number, error_msg)

            return None

        except (IOError, OSError) as e:
            # File system errors - may be recoverable
            error_msg = f"File system error for {cik}/{accession_number}: {e}"
            logger.error(error_msg, exc_info=True)

            if self.db:
                self._update_database_error(cik, accession_number, error_msg)

            return None

        except Exception as e:
            # Unexpected errors - log with full traceback for debugging
            error_msg = (
                f"Unexpected error fetching {cik}/{accession_number}: "
                f"{type(e).__name__}: {e}"
            )
            logger.critical(error_msg, exc_info=True)

            if self.db:
                self._update_database_error(cik, accession_number, error_msg)

            return None

    def _update_database(
        self,
        content: FilingContent,
        error: Optional[str],
        resolved_url: Optional[str] = None,
    ) -> bool:
        """
        Update database to mark filing as fetched.

        Args:
            content: Filing content with paths and metadata
            error: Error message if any (unused, kept for API compatibility)
            resolved_url: Resolved SEC document URL (replaces directory URL)

        Returns:
            True if database update succeeded, False otherwise
        """
        try:
            query = """
                UPDATE filings
                SET
                    html_storage_path = %(html_path)s,
                    txt_storage_path = %(txt_path)s,
                    html_fetched_at = %(fetched_at)s,
                    html_fetch_error = NULL,
                    processing_status = 'fetched',
                    sec_html_url = COALESCE(%(resolved_url)s, sec_html_url),
                    updated_at = now()
                WHERE accession_number = %(accession)s
            """
            self.db.execute(
                query,
                {
                    "html_path": content.html_path,
                    "txt_path": content.txt_path,
                    "fetched_at": content.fetched_at,
                    "accession": content.accession_number,
                    "resolved_url": resolved_url,
                },
            )
            logger.debug(f"Updated database for {content.accession_number}")
            return True
        except Exception as e:
            logger.error(
                f"Error updating database for {content.accession_number}: {e}",
                exc_info=True,
            )
            return False

    def _update_database_error(
        self, cik: str, accession_number: str, error_msg: str
    ) -> bool:
        """
        Update database to record fetch error.

        Args:
            cik: SEC Central Index Key
            accession_number: SEC accession number
            error_msg: Error message describing the fetch failure

        Returns:
            True if database update succeeded, False otherwise
        """
        try:
            query = """
                UPDATE filings
                SET
                    html_fetch_error = %(error)s,
                    updated_at = now()
                WHERE accession_number = %(accession)s
            """
            self.db.execute(
                query,
                {"error": error_msg, "accession": accession_number},
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to record fetch error in database for {accession_number}. "
                f"Original error: {error_msg}, DB error: {e}",
                exc_info=True,
            )
            return False

    def get_filing_content(
        self, cik: str, accession_number: str
    ) -> Optional[FilingContent]:
        """
        Get cached filing content if it exists.

        Args:
            cik: SEC Central Index Key
            accession_number: SEC accession number

        Returns:
            FilingContent if cached, None otherwise
        """
        storage_dir = self._get_storage_dir(cik, accession_number)
        html_path = storage_dir / "primary.htm"
        txt_path = storage_dir / "complete.txt"

        if not html_path.exists():
            return None

        return FilingContent(
            cik=cik,
            accession_number=accession_number,
            html_path=str(html_path),
            txt_path=str(txt_path) if txt_path.exists() else None,
        )

    def fetch_batch(
        self,
        filings: List[FilingMetadata],
        fetch_txt: bool = True,
        max_failures: int = 10,
    ) -> dict:
        """
        Fetch multiple filings in sequence.

        Args:
            filings: List of FilingMetadata to fetch
            fetch_txt: Whether to fetch TXT files
            max_failures: Stop after this many consecutive failures

        Returns:
            Dict with statistics: {
                'total': int,
                'fetched': int,
                'failed': int,
                'skipped': int (already cached)
            }
        """
        stats = {
            "total": len(filings),
            "fetched": 0,
            "failed": 0,
            "skipped": 0,
        }

        consecutive_failures = 0

        for i, filing in enumerate(filings, 1):
            logger.info(f"Processing {i}/{len(filings)}: {filing.company_name}")

            # Check if already cached
            existing = self.get_filing_content(filing.cik, filing.accession_number)
            if existing:
                logger.debug("Already cached, skipping")
                stats["skipped"] += 1
                consecutive_failures = 0
                continue

            # Fetch filing
            result = self.fetch_filing(filing, fetch_txt=fetch_txt)

            if result:
                stats["fetched"] += 1
                consecutive_failures = 0
            else:
                stats["failed"] += 1
                consecutive_failures += 1

                if consecutive_failures >= max_failures:
                    logger.error(f"Stopping after {max_failures} consecutive failures")
                    break

        logger.info(f"Batch fetch complete: {stats}")
        return stats

    def get_unfetched_filings(self, limit: int = 100) -> List[dict]:
        """
        Get list of in-scope filings that haven't been fetched yet.

        Args:
            limit: Maximum number to return

        Returns:
            List of filing records from database
        """
        if not self.db:
            raise ValueError("Database required for get_unfetched_filings")

        query = """
            SELECT
                f.filing_id,
                f.company_id,
                c.company_name,
                f.cik,
                f.accession_number,
                f.form_type,
                f.filing_date,
                f.sec_html_url as primary_doc_url,
                f.sec_txt_url as txt_url,
                f.processing_status,
                f.created_at
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE
                f.is_in_scope_phase1 = true
                AND f.html_fetched_at IS NULL
                AND (f.html_fetch_error IS NULL OR f.html_fetch_error = '')
            ORDER BY RANDOM()
            LIMIT %(limit)s
        """

        return self.db.query(query, {"limit": limit})
