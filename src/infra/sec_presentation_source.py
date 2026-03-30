"""
SEC Presentation Source — Fetch investor presentations from SEC 8-K filings.

Implements the DocumentSource protocol using EDGAR submissions API:
- list_available(ticker) → list of DocumentMetadata for presentation exhibits
- fetch(source_id) → HTML string + DocumentMetadata

Source ID format:
    ``{cik}/{accession_number}/{filename}``
    Example: ``0001234567/0001234567-24-000001/presentation.pdf``

Caching:
    PDF and HTML are cached under data/presentations/{ticker}/{accession}/{filename}.
    fetch() is idempotent: returns cached HTML on subsequent calls.

Usage:
    >>> from src.infra.sec_presentation_source import SECPresentationSource
    >>> source = SECPresentationSource()
    >>> docs = source.list_available(ticker="CRM")
    >>> html, metadata = source.fetch(docs[0].source_id)
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, cast

import requests

from src.infra.document_source import DocumentMetadata
from src.infra.sec_client import SECClient

# presentation_converter is implemented in parallel — import gracefully
try:
    from src.extraction_v2.presentation_converter import convert_presentation_to_html
except ImportError:  # pragma: no cover
    convert_presentation_to_html = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# EDGAR base URLs
_EDGAR_BASE = "https://www.sec.gov"
_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"

# Source identifier
SOURCE_NAME = "sec_edgar_presentation"

# Default cache location
DEFAULT_CACHE_DIR = Path("data/presentations")

# User-agent for direct requests (SEC requires contact info)
_DEFAULT_USER_AGENT = os.environ.get("SEC_USER_AGENT", "filings-reviewer info@example.com")


class SECPresentationSource:
    """DocumentSource for investor presentations from SEC 8-K filings.

    Implements the DocumentSource protocol.

    Discovery strategy:
    - Resolve ticker → CIK via EDGAR submissions API
    - Walk the company's 8-K filings (recent + archived)
    - Filter exhibits to PDF/HTM files whose filename either contains a
      presentation keyword (presentation, slides, investor, earnings) or
      matches the exhibit99 filename pattern (e.g. ``exhibit991``, ``exhibit99``)

    Caching strategy:
    - PDF stored at cache_dir/{ticker}/{accession}/{filename}
    - HTML stored at cache_dir/{ticker}/{accession}/{filename}.html
    - Metadata stored at cache_dir/{ticker}/{accession}/{filename}.meta.json
    - Idempotent: subsequent fetch() calls return the cached HTML
    """

    PRESENTATION_KEYWORDS: tuple[str, ...] = (
        "presentation",
        "slides",
        "investor",
        "earnings",
    )
    EXHIBIT_TYPES: tuple[str, ...] = ("EX-99.1", "EX-99.2", "EX-99")

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        sec_client: SECClient | None = None,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        """Initialize the SEC presentation source.

        Args:
            cache_dir: Local directory for caching downloaded presentations.
            sec_client: Optional pre-configured SECClient. If None, creates one
                with the provided user_agent.
            user_agent: User-Agent header for EDGAR requests. Must include
                company name and contact email per SEC policy.
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent

        if sec_client is None:
            self._sec_client = SECClient(user_agent=user_agent)
        else:
            self._sec_client = sec_client

        # Session for direct EDGAR binary downloads (PDFs)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

        # Instance-level cache: CIK → ticker (avoids class-level data bleed)
        self._cik_to_ticker_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API (DocumentSource protocol)
    # ------------------------------------------------------------------

    def list_available(
        self,
        ticker: str | None = None,
        company_name: str | None = None,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        """List investor presentation exhibits available for a ticker.

        Args:
            ticker: Stock ticker symbol (required for meaningful results).
            company_name: Unused; included for protocol compatibility.
            limit: Maximum number of results to return.

        Returns:
            List of DocumentMetadata, one per matching exhibit file.
            Returns an empty list if the ticker is not found or has no
            matching 8-K exhibits.
        """
        if not ticker:
            logger.warning("list_available called with no ticker — returning empty list")
            return []

        cik, company = self._resolve_ticker(ticker)
        if cik is None:
            logger.warning("Ticker %s not found in EDGAR submissions", ticker)
            return []

        results: list[DocumentMetadata] = []

        for exhibit_info in self._iter_presentation_exhibits(cik, ticker, limit):
            meta = self._exhibit_to_metadata(exhibit_info, company)
            results.append(meta)
            if len(results) >= limit:
                break

        logger.info("Found %d presentation exhibits for %s (CIK %s)", len(results), ticker, cik)
        return results

    def fetch(self, source_id: str) -> tuple[str, DocumentMetadata]:
        """Download a presentation (PDF or HTM), convert if needed, and cache locally.

        For ``.htm`` files: downloads HTML directly from EDGAR and caches it as-is.
        For ``.pdf`` files: downloads the binary, converts to HTML via
        ``convert_presentation_to_html``, then caches.

        Args:
            source_id: ``{cik}/{accession_number}/{filename}`` as returned by
                list_available().

        Returns:
            Tuple of (html_string, DocumentMetadata).

        Raises:
            ValueError: If source_id format is invalid.
            FileNotFoundError: If the file cannot be downloaded and is not cached.
        """
        cik, accession, filename = self._parse_source_id(source_id)

        # Determine cache paths
        ticker_hint = self._cik_to_ticker_cache.get(cik, cik)
        html_path, meta_path = self._cache_paths(ticker_hint, accession, filename)

        # Cache hit — return immediately
        if html_path.exists() and meta_path.exists():
            logger.debug("Cache hit for %s", source_id)
            html = html_path.read_text(encoding="utf-8")
            metadata = self._load_cached_metadata(meta_path)
            return html, metadata

        filename_lower = filename.lower()
        is_htm = filename_lower.endswith(".htm") or filename_lower.endswith(".html")

        if is_htm:
            # HTM path: download the HTML directly, no PDF conversion needed
            html = self._download_htm(cik, accession, filename)
            if html is None:
                raise FileNotFoundError(f"Could not download HTM for source_id={source_id}")
        else:
            # PDF path: download binary → convert to HTML
            pdf_path = html_path.parent / filename
            if not pdf_path.exists():
                pdf_bytes = self._download_pdf(cik, accession, filename)
                if pdf_bytes is None:
                    raise FileNotFoundError(f"Could not download PDF for source_id={source_id}")
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(pdf_bytes)
                logger.debug("Saved PDF to %s (%d bytes)", pdf_path, len(pdf_bytes))

            # Convert PDF to HTML
            if convert_presentation_to_html is None:
                raise ImportError(
                    "src.extraction_v2.presentation_converter is not available. "
                    "Install presentation_converter dependencies."
                )
            try:
                html, _presentation_meta = convert_presentation_to_html(pdf_path)
            except Exception as exc:
                logger.warning("Conversion failed for %s: %s", source_id, exc)
                raise

        # Build and cache metadata
        metadata = DocumentMetadata(
            source_id=source_id,
            source=SOURCE_NAME,
            cik=cik,
            document_type="investor_presentation",
            form_type="8-K",
        )
        # Try to enrich from the company info
        try:
            info = self._sec_client.get_company_info(cik)
            if info:
                metadata.company_name = info.get("name")
                tickers = info.get("tickers", [])
                metadata.ticker = tickers[0] if tickers else None
        except Exception as exc:
            logger.debug("Could not enrich metadata for CIK %s: %s", cik, exc)

        # Persist cache
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        meta_path.write_text(
            json.dumps(self._metadata_to_dict(metadata), indent=2), encoding="utf-8"
        )
        logger.debug("Cached HTML to %s", html_path)

        return html, metadata

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_ticker(self, ticker: str) -> tuple[str | None, str | None]:
        """Resolve a ticker to (cik, company_name) using EDGAR submissions API.

        Returns (None, None) if the ticker cannot be resolved.
        """
        # Use the EDGAR company tickers JSON to map ticker → CIK
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            self._sec_client._rate_limit()
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            tickers_map: dict[str, dict[str, Any]] = resp.json()

            ticker_upper = ticker.upper()
            for entry in tickers_map.values():
                if entry.get("ticker", "").upper() == ticker_upper:
                    cik_raw = str(entry["cik_str"])
                    cik = cik_raw.zfill(10)
                    company = entry.get("title", "")
                    self._cik_to_ticker_cache[cik] = ticker_upper
                    return cik, company

            logger.warning("Ticker %s not found in EDGAR company_tickers.json", ticker)
            return None, None

        except requests.RequestException as exc:
            logger.error("Failed to fetch company tickers from EDGAR: %s", exc)
            return None, None

    def _iter_presentation_exhibits(
        self, cik: str, ticker: str, limit: int
    ) -> list[dict[str, Any]]:
        """Walk 8-K filings for a CIK and yield matching exhibit metadata."""
        results: list[dict[str, Any]] = []

        submissions_url = f"{_SUBMISSIONS_BASE}/CIK{cik}.json"
        try:
            data = self._sec_client._make_request(submissions_url)
        except Exception as exc:
            logger.error("Failed to fetch submissions for CIK %s: %s", cik, exc)
            return results

        company_name = data.get("name", "")
        self._cik_to_ticker_cache[cik] = ticker.upper()

        # Process recent + archived filing arrays
        filing_arrays: list[dict[str, Any]] = []
        recent = data.get("filings", {}).get("recent", {})
        filing_arrays.append(recent)

        for file_info in data.get("filings", {}).get("files", []):
            fname = file_info.get("name", "")
            if fname:
                try:
                    archived = self._sec_client._make_request(f"{_SUBMISSIONS_BASE}/{fname}")
                    filing_arrays.append(archived)
                except Exception as exc:
                    logger.warning("Could not fetch archived filings %s: %s", fname, exc)

        for filings_data in filing_arrays:
            batch = self._extract_exhibits_from_filings_array(
                filings_data, cik, ticker, company_name
            )
            results.extend(batch)
            if len(results) >= limit:
                break

        return results[:limit]

    def _extract_exhibits_from_filings_array(
        self,
        filings_data: dict[str, Any],
        cik: str,
        ticker: str,
        company_name: str,
    ) -> list[dict[str, Any]]:
        """Extract matching presentation exhibits from a filings array dict."""
        results: list[dict[str, Any]] = []

        forms = filings_data.get("form", [])
        accession_numbers = filings_data.get("accessionNumber", [])
        filing_dates = filings_data.get("filingDate", [])

        for i, form in enumerate(forms):
            if form != "8-K":
                continue

            accession = accession_numbers[i] if i < len(accession_numbers) else ""
            filing_date = filing_dates[i] if i < len(filing_dates) else ""

            if not accession:
                continue

            exhibits = self._get_8k_exhibits(cik, accession)
            for exhibit in exhibits:
                results.append(
                    {
                        "source_id": f"{cik}/{accession}/{exhibit['filename']}",
                        "ticker": ticker.upper(),
                        "cik": cik,
                        "company_name": company_name,
                        "form_type": "8-K",
                        "filing_date": filing_date,
                        "exhibit_type": exhibit["exhibit_type"],
                        "filename": exhibit["filename"],
                        "accession_number": accession,
                    }
                )

        return results

    def _get_8k_exhibits(self, cik: str, accession_number: str) -> list[dict[str, str]]:
        """Fetch the filing index for an 8-K and return matching PDF/HTM exhibits.

        Uses filename-based heuristics to identify EX-99.x earnings releases:
        - Accepts both ``.pdf`` and ``.htm`` files
        - Matches if the filename contains a presentation keyword (presentation,
          slides, investor, earnings) OR matches the exhibit99 filename pattern
          (e.g. ``exhibit991``, ``exhibit99``)

        Note: EDGAR's index.json returns ``"type"`` as a file icon type (e.g.
        ``"text.gif"``), NOT the SEC exhibit type — so we do not use it for
        exhibit type filtering.
        """
        accession_clean = accession_number.replace("-", "")
        index_url = (
            f"{_EDGAR_BASE}/Archives/edgar/data/{cik.lstrip('0') or '0'}/"
            f"{accession_clean}/index.json"
        )

        try:
            data = self._sec_client._make_request(index_url)
        except Exception as exc:
            logger.debug("Could not fetch index for %s/%s: %s", cik, accession_number, exc)
            return []

        items = data.get("directory", {}).get("item", [])
        matching: list[dict[str, str]] = []

        for item in items:
            name = item.get("name", "")
            name_lower = name.lower()

            # Must be a PDF or HTM file
            is_pdf = name_lower.endswith(".pdf")
            is_htm = name_lower.endswith(".htm") or name_lower.endswith(".html")
            if not is_pdf and not is_htm:
                continue

            # Filename must contain a presentation keyword OR match exhibit99 pattern
            has_keyword = any(kw in name_lower for kw in self.PRESENTATION_KEYWORDS)
            is_exhibit99 = bool(re.search(r"exhibit9[0-9]", name_lower))
            if not has_keyword and not is_exhibit99:
                continue

            matching.append({"filename": name, "exhibit_type": "", "is_pdf": str(is_pdf)})

        return matching

    def _download_pdf(self, cik: str, accession_number: str, filename: str) -> bytes | None:
        """Download a PDF exhibit from EDGAR.

        Returns raw bytes on success, None on failure.
        """
        accession_clean = accession_number.replace("-", "")
        cik_stripped = cik.lstrip("0") or "0"
        url = f"{_EDGAR_BASE}/Archives/edgar/data/{cik_stripped}/{accession_clean}/{filename}"

        try:
            self._sec_client._rate_limit()
            resp = self._session.get(url, timeout=60)
            resp.raise_for_status()
            logger.debug("Downloaded PDF %s (%d bytes)", url, len(resp.content))
            return cast(bytes, resp.content)
        except requests.RequestException as exc:
            logger.warning("Failed to download PDF from %s: %s", url, exc)
            return None

    def _download_htm(self, cik: str, accession_number: str, filename: str) -> str | None:
        """Download an HTM exhibit from EDGAR.

        Returns the HTML string on success, None on failure.
        """
        accession_clean = accession_number.replace("-", "")
        cik_stripped = cik.lstrip("0") or "0"
        url = f"{_EDGAR_BASE}/Archives/edgar/data/{cik_stripped}/{accession_clean}/{filename}"

        try:
            self._sec_client._rate_limit()
            resp = self._session.get(url, timeout=60)
            resp.raise_for_status()
            logger.debug("Downloaded HTM %s (%d bytes)", url, len(resp.content))
            return cast(str, resp.text)
        except requests.RequestException as exc:
            logger.warning("Failed to download HTM from %s: %s", url, exc)
            return None

    def _cache_paths(self, ticker: str, accession_number: str, filename: str) -> tuple[Path, Path]:
        """Return (html_path, meta_path) for caching a given exhibit."""
        base = self.cache_dir / ticker.upper() / accession_number / filename
        return base.with_suffix(base.suffix + ".html"), base.with_suffix(base.suffix + ".meta.json")

    @staticmethod
    def _parse_source_id(source_id: str) -> tuple[str, str, str]:
        """Parse source_id into (cik, accession_number, filename).

        Raises:
            ValueError: If format is invalid.
        """
        parts = source_id.split("/", 2)
        if len(parts) != 3:
            raise ValueError(
                f"Invalid source_id format: {source_id!r}. "
                "Expected '{cik}/{accession_number}/{filename}'."
            )
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _exhibit_to_metadata(exhibit: dict[str, Any], company: str | None) -> DocumentMetadata:
        """Convert an exhibit info dict to DocumentMetadata."""
        doc_date: date | None = None
        raw_date = exhibit.get("filing_date", "")
        if raw_date:
            try:
                doc_date = date.fromisoformat(raw_date[:10])
            except (ValueError, TypeError):
                pass

        return DocumentMetadata(
            source_id=exhibit["source_id"],
            source=SOURCE_NAME,
            company_name=exhibit.get("company_name") or company,
            ticker=exhibit.get("ticker"),
            cik=exhibit.get("cik"),
            document_type="investor_presentation",
            document_date=doc_date,
            title=exhibit.get("filename"),
            form_type="8-K",
            url=(
                f"{_EDGAR_BASE}/Archives/edgar/data/"
                f"{(exhibit.get('cik') or '').lstrip('0') or '0'}/"
                f"{exhibit.get('accession_number', '').replace('-', '')}/"
                f"{exhibit.get('filename', '')}"
            ),
        )

    @staticmethod
    def _metadata_to_dict(meta: DocumentMetadata) -> dict[str, Any]:
        """Serialize DocumentMetadata to a JSON-safe dict."""
        return {
            "source_id": meta.source_id,
            "source": meta.source,
            "company_name": meta.company_name,
            "ticker": meta.ticker,
            "cik": meta.cik,
            "document_type": meta.document_type,
            "document_date": meta.document_date.isoformat() if meta.document_date else None,
            "title": meta.title,
            "fiscal_year": meta.fiscal_year,
            "fiscal_period": meta.fiscal_period,
            "form_type": meta.form_type,
            "url": meta.url,
        }

    @staticmethod
    def _load_cached_metadata(meta_path: Path) -> DocumentMetadata:
        """Load DocumentMetadata from a cached .meta.json file."""
        d: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
        doc_date: date | None = None
        if d.get("document_date"):
            try:
                doc_date = date.fromisoformat(d["document_date"])
            except (ValueError, TypeError):
                pass

        return DocumentMetadata(
            source_id=d.get("source_id", ""),
            source=d.get("source", SOURCE_NAME),
            company_name=d.get("company_name"),
            ticker=d.get("ticker"),
            cik=d.get("cik"),
            document_type=d.get("document_type", "investor_presentation"),
            document_date=doc_date,
            title=d.get("title"),
            fiscal_year=d.get("fiscal_year"),
            fiscal_period=d.get("fiscal_period"),
            form_type=d.get("form_type"),
            url=d.get("url"),
        )
