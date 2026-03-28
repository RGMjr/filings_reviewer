"""
Financial Modeling Prep (FMP) Transcript Source — Fetch earnings call transcripts.

Implements the DocumentSource protocol using the FMP API:
- list_available(ticker) → list of transcript metadata for that ticker
- fetch(source_id) → HTML string + DocumentMetadata

API key:
    Set the FMP_API_KEY environment variable. Get a key at:
    https://financialmodelingprep.com/developer/docs/

Rate limits:
    FMP free tier: 300 requests/minute, 250 transcripts/month.
    A simple inter-request delay (0.2s) keeps well within the rate limit.

Caching:
    HTML and metadata are cached under data/transcripts/fmp/ with a 30-day TTL.
    Re-runs within the TTL window use the cache and do not hit the API.

Source ID format:
    ``fmp:{ticker}_{date}_{quarter}``
    Example: ``fmp:CRM_2025-02-26_Q4``

Usage:
    >>> import os
    >>> os.environ["FMP_API_KEY"] = "your-key"
    >>> from src.infra.fmp_source import FMPTranscriptSource
    >>> source = FMPTranscriptSource()
    >>> docs = source.list_available(ticker="CRM")
    >>> html, metadata = source.fetch(docs[0].source_id)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.extraction_v2.transcript_converter import convert_transcript_to_html
from src.infra.document_source import DocumentMetadata

logger = logging.getLogger(__name__)

# FMP API base URL
_FMP_BASE = "https://financialmodelingprep.com/stable"

# Source identifier prefix
SOURCE_PREFIX = "fmp"

# Default cache location
DEFAULT_CACHE_DIR = Path("data/transcripts/fmp")

# Cache TTL
_CACHE_TTL_DAYS = 30

# Minimum delay between API requests (seconds) to stay within 300 req/min
_REQUEST_DELAY_SECS = 0.21


def _build_source_id(ticker: str, doc_date: str, quarter: str) -> str:
    """Build a stable source_id from ticker, date, and quarter."""
    safe_date = doc_date[:10] if doc_date else "unknown"
    safe_q = quarter.replace(" ", "") if quarter else "unknown"
    return f"{SOURCE_PREFIX}:{ticker.upper()}_{safe_date}_{safe_q}"


def _is_cache_fresh(path: Path) -> bool:
    """Return True if the cache file exists and is within the TTL."""
    if not path.exists():
        return False
    age = datetime.utcnow() - datetime.utcfromtimestamp(path.stat().st_mtime)
    return age < timedelta(days=_CACHE_TTL_DAYS)


class FMPTranscriptSource:
    """
    Fetch earnings call transcripts from the FMP API.

    Implements the DocumentSource protocol.

    Caching strategy:
    - list_available() results cached per-ticker (30-day TTL)
    - fetch() HTML cached per source_id (30-day TTL)
    - Stale cache entries are refreshed transparently
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
    ) -> None:
        """
        Initialize the FMP transcript source.

        Args:
            api_key: FMP API key. Falls back to FMP_API_KEY env var.
            cache_dir: Local directory for caching downloaded transcripts.

        Raises:
            ValueError: If no API key is available.
        """
        resolved_key = api_key or os.environ.get("FMP_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "FMP_API_KEY is required. Set the environment variable or pass "
                "api_key= to FMPTranscriptSource()."
            )
        self._api_key = resolved_key
        self.cache_dir = cache_dir

        # Ensure cache subdirs
        self._html_dir = cache_dir / "html"
        self._index_dir = cache_dir / "index"
        self._html_dir.mkdir(parents=True, exist_ok=True)
        self._index_dir.mkdir(parents=True, exist_ok=True)

        self._last_request_at: float = 0.0

    # -------------------------------------------------------------------------
    # Public DocumentSource interface
    # -------------------------------------------------------------------------

    def list_available(
        self,
        ticker: str | None = None,
        company_name: str | None = None,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        """
        List available transcripts for a ticker.

        Args:
            ticker: Required. FMP requires a specific ticker to list transcripts.
            company_name: Ignored (FMP doesn't support company name search).
            limit: Maximum number of results to return.

        Returns:
            List of DocumentMetadata for available transcripts, newest first.

        Raises:
            ValueError: If ticker is not provided.
        """
        if not ticker:
            raise ValueError(
                "FMPTranscriptSource.list_available() requires a ticker symbol."
            )

        raw_entries = self._fetch_index(ticker.upper())

        results: list[DocumentMetadata] = []
        for entry in raw_entries:
            results.append(self._entry_to_metadata(entry))
            if len(results) >= limit:
                break

        return results

    def fetch(self, source_id: str) -> tuple[str, DocumentMetadata]:
        """
        Fetch a transcript by source_id, returning HTML and metadata.

        Uses cached HTML if within the TTL, otherwise downloads and converts.

        Args:
            source_id: Source ID from list_available() in format
                       ``fmp:{ticker}_{date}_{quarter}``

        Returns:
            Tuple of (html_content, metadata)

        Raises:
            FileNotFoundError: If source_id not found.
            ValueError: If source_id format is invalid.
        """
        if not source_id.startswith(f"{SOURCE_PREFIX}:"):
            raise ValueError(f"Invalid FMP source_id: {source_id!r}")

        cache_html = self._html_dir / f"{source_id.replace(':', '_')}.html"
        cache_meta = self._html_dir / f"{source_id.replace(':', '_')}.meta.json"

        if _is_cache_fresh(cache_html) and _is_cache_fresh(cache_meta):
            logger.debug("Cache hit for %s", source_id)
            html = cache_html.read_text(encoding="utf-8")
            meta_dict = json.loads(cache_meta.read_text())
            return html, self._dict_to_metadata(meta_dict)

        # Parse source_id to find ticker/date/quarter for the API call
        # Format: fmp:{TICKER}_{DATE}_{QUARTER}
        rest = source_id[len(SOURCE_PREFIX) + 1:]  # strip "fmp:"
        parts = rest.split("_", 2)
        if len(parts) < 2:
            raise ValueError(f"Cannot parse ticker from source_id: {source_id!r}")
        ticker = parts[0]

        # Re-fetch the index to locate the entry
        raw_entries = self._fetch_index(ticker)
        entry = next((e for e in raw_entries if e.get("source_id") == source_id), None)
        if entry is None:
            raise FileNotFoundError(
                f"Transcript {source_id!r} not found in FMP index for {ticker}."
            )

        # Convert raw text to HTML
        raw_text = entry.get("content", "")
        title = (
            f"{entry.get('symbol', ticker)} Earnings Call "
            f"{entry.get('quarter', '')} {entry.get('year', '')}".strip()
        )
        html, _converter_meta = convert_transcript_to_html(raw_text, title=title)
        metadata = self._entry_to_metadata(entry)

        # Cache
        cache_html.write_text(html, encoding="utf-8")
        cache_meta.write_text(json.dumps(self._metadata_to_dict(metadata), indent=2))

        logger.info("Fetched and cached transcript %s (%d chars)", source_id, len(html))
        return html, metadata

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Enforce the minimum delay between API requests."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _REQUEST_DELAY_SECS:
            time.sleep(_REQUEST_DELAY_SECS - elapsed)
        self._last_request_at = time.monotonic()

    def _fetch_index(self, ticker: str) -> list[dict[str, Any]]:
        """
        Fetch and cache the transcript index for a ticker.

        Returns list of raw entry dicts from the FMP API (with source_id added).
        """
        cache_path = self._index_dir / f"{ticker.upper()}.json"

        if _is_cache_fresh(cache_path):
            logger.debug("Index cache hit for %s", ticker)
            raw = json.loads(cache_path.read_text())
        else:
            raw = self._call_api_list(ticker)
            # Annotate each entry with a stable source_id
            for entry in raw:
                q = entry.get("quarter", "")
                y = entry.get("year", "")
                quarter_str = f"Q{q}" if q else "unknown"
                year_str = str(y) if y else ""
                label = f"{quarter_str}{year_str}"
                entry["source_id"] = _build_source_id(
                    entry.get("symbol", ticker),
                    entry.get("date", ""),
                    label,
                )
            cache_path.write_text(json.dumps(raw, indent=2))
            logger.info("Cached index for %s: %d transcripts", ticker, len(raw))

        return raw

    def _call_api_list(self, ticker: str) -> list[dict[str, Any]]:
        """
        Call the FMP earnings-call-transcript list endpoint.

        Returns list of transcript dicts sorted newest-first.
        """
        import urllib.error
        import urllib.request

        url = (
            f"{_FMP_BASE}/earnings-call-transcript"
            f"?symbol={ticker}&apikey={self._api_key}"
        )
        self._rate_limit()

        try:
            logger.debug("FMP API: GET %s", url.replace(self._api_key, "***"))
            with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
                data: list[dict[str, Any]] = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            logger.error("FMP API error for %s: HTTP %s", ticker, exc.code)
            return []
        except OSError as exc:
            logger.error("FMP network error for %s: %s", ticker, exc)
            return []

        if not isinstance(data, list):
            logger.warning("FMP API returned unexpected format for %s", ticker)
            return []

        # Sort newest first by date
        data.sort(key=lambda e: e.get("date", ""), reverse=True)
        return data

    def _entry_to_metadata(self, entry: dict[str, Any]) -> DocumentMetadata:
        """Convert a raw FMP API entry to DocumentMetadata."""
        doc_date: date | None = None
        if entry.get("date"):
            try:
                doc_date = datetime.strptime(entry["date"][:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        q = entry.get("quarter", "")
        y = entry.get("year", "")
        fiscal_period = f"Q{q}" if q else None
        fiscal_year: int | None = None
        if y:
            try:
                fiscal_year = int(y)
            except (ValueError, TypeError):
                pass

        ticker = entry.get("symbol", "")
        quarter_label = f"Q{q}{y}" if q else "unknown"

        return DocumentMetadata(
            source_id=entry.get(
                "source_id",
                _build_source_id(ticker, entry.get("date", ""), quarter_label),
            ),
            source=f"{SOURCE_PREFIX}:financialmodelingprep.com",
            ticker=ticker or None,
            company_name=entry.get("company_name"),
            document_type="earnings_call",
            document_date=doc_date,
            title=f"{ticker} Earnings Call {fiscal_period or ''} {y or ''}".strip(),
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            form_type="earnings_call",
        )

    @staticmethod
    def _metadata_to_dict(meta: DocumentMetadata) -> dict[str, Any]:
        """Serialize DocumentMetadata to a JSON-safe dict."""
        return {
            "source_id": meta.source_id,
            "source": meta.source,
            "ticker": meta.ticker,
            "company_name": meta.company_name,
            "document_type": meta.document_type,
            "document_date": meta.document_date.isoformat() if meta.document_date else None,
            "title": meta.title,
            "fiscal_year": meta.fiscal_year,
            "fiscal_period": meta.fiscal_period,
            "form_type": meta.form_type,
        }

    @staticmethod
    def _dict_to_metadata(d: dict[str, Any]) -> DocumentMetadata:
        """Deserialize DocumentMetadata from a JSON dict."""
        doc_date: date | None = None
        if d.get("document_date"):
            try:
                doc_date = date.fromisoformat(d["document_date"])
            except (ValueError, TypeError):
                pass

        return DocumentMetadata(
            source_id=d.get("source_id", ""),
            source=d.get("source", ""),
            ticker=d.get("ticker"),
            company_name=d.get("company_name"),
            document_type=d.get("document_type", "earnings_call"),
            document_date=doc_date,
            title=d.get("title"),
            fiscal_year=d.get("fiscal_year"),
            fiscal_period=d.get("fiscal_period"),
            form_type=d.get("form_type"),
        )
