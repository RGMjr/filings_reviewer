"""
HuggingFace Transcript Source — Fetch earnings call transcripts from HuggingFace datasets.

Wraps the `kurry/sp500_earnings_transcripts` dataset (or similar) with:
- Local caching to data/transcripts/ (download once, reuse)
- HTML conversion via transcript_converter
- DocumentSource protocol compliance

Usage:
    >>> from src.infra.huggingface_source import HuggingFaceTranscriptSource
    >>> source = HuggingFaceTranscriptSource()
    >>> docs = source.list_available(ticker="SNOW")
    >>> html, metadata = source.fetch(docs[0].source_id)

Requires: pip install datasets
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.extraction_v2.transcript_converter import convert_transcript_to_html
from src.infra.document_source import DocumentMetadata, DocumentSource

logger = logging.getLogger(__name__)

# Default dataset
DEFAULT_DATASET = "kurry/sp500_earnings_transcripts"
DEFAULT_CACHE_DIR = Path("data/transcripts")

# Source identifier
SOURCE_PREFIX = "huggingface"


class HuggingFaceTranscriptSource:
    """
    Fetch earnings call transcripts from a HuggingFace dataset.

    Implements the DocumentSource protocol.

    Caching strategy:
    - On first call to list_available(), downloads dataset index
    - On fetch(), downloads individual transcript and caches as HTML
    - Subsequent calls use cached files
    """

    def __init__(
        self,
        dataset_name: str = DEFAULT_DATASET,
        cache_dir: Path = DEFAULT_CACHE_DIR,
    ) -> None:
        """
        Initialize the HuggingFace transcript source.

        Args:
            dataset_name: HuggingFace dataset identifier
            cache_dir: Local directory for caching downloaded transcripts
        """
        self.dataset_name = dataset_name
        self.cache_dir = cache_dir
        self.source_name = f"{SOURCE_PREFIX}:{dataset_name}"
        self._index: list[dict[str, Any]] | None = None

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._html_dir = self.cache_dir / "html"
        self._html_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.cache_dir / "index.json"

    def _ensure_index(self) -> list[dict[str, Any]]:
        """Load or build the dataset index."""
        if self._index is not None:
            return self._index

        # Try cached index first
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text())
                return self._index
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupted index cache, rebuilding")

        # Download dataset index
        try:
            from datasets import load_dataset  # type: ignore

            logger.info("Downloading dataset index from %s...", self.dataset_name)
            dataset = load_dataset(self.dataset_name, split="train")

            self._index = []
            for i, row in enumerate(dataset):
                entry = {
                    "idx": i,
                    "ticker": row.get("ticker", ""),
                    "company_name": row.get("company", row.get("company_name", "")),
                    "date": row.get("date", ""),
                    "title": row.get("title", ""),
                    "quarter": row.get("quarter", ""),
                    "year": row.get("year", ""),
                }
                # Generate stable source_id from content hash
                content_key = f"{entry['ticker']}_{entry['date']}_{i}"
                entry["source_id"] = hashlib.md5(content_key.encode()).hexdigest()[:12]
                self._index.append(entry)

            # Cache index
            self._index_path.write_text(json.dumps(self._index, indent=2))
            logger.info("Cached index with %d transcripts", len(self._index))

        except ImportError:
            logger.error(
                "datasets package not installed. Run: pip install datasets"
            )
            self._index = []
        except Exception as e:
            logger.error("Failed to load dataset %s: %s", self.dataset_name, e)
            self._index = []

        return self._index

    def list_available(
        self,
        ticker: str | None = None,
        company_name: str | None = None,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        """List available transcripts, optionally filtered by ticker or company."""
        index = self._ensure_index()
        results: list[DocumentMetadata] = []

        for entry in index:
            if ticker and entry.get("ticker", "").upper() != ticker.upper():
                continue
            if company_name and company_name.lower() not in entry.get("company_name", "").lower():
                continue

            meta = self._entry_to_metadata(entry)
            results.append(meta)

            if len(results) >= limit:
                break

        return results

    def fetch(self, source_id: str) -> tuple[str, DocumentMetadata]:
        """
        Fetch a transcript by source_id, returning HTML and metadata.

        Uses cached HTML if available, otherwise downloads and converts.

        Args:
            source_id: Source-specific ID from list_available()

        Returns:
            Tuple of (html_content, metadata)

        Raises:
            FileNotFoundError: If source_id not found in dataset
        """
        # Check cache first
        cache_path = self._html_dir / f"{source_id}.html"
        meta_path = self._html_dir / f"{source_id}.meta.json"

        if cache_path.exists() and meta_path.exists():
            html = cache_path.read_text(encoding="utf-8")
            meta_dict = json.loads(meta_path.read_text())
            metadata = self._dict_to_metadata(meta_dict)
            return html, metadata

        # Find entry in index
        index = self._ensure_index()
        entry = next((e for e in index if e["source_id"] == source_id), None)
        if not entry:
            raise FileNotFoundError(f"Transcript {source_id} not found in dataset")

        # Download raw text
        try:
            from datasets import load_dataset  # type: ignore

            dataset = load_dataset(self.dataset_name, split="train")
            row = dataset[entry["idx"]]
            raw_text = row.get("text", row.get("transcript", ""))
        except ImportError:
            raise ImportError("datasets package not installed. Run: pip install datasets")

        # Convert to HTML
        title = entry.get("title", f"{entry.get('ticker', 'Unknown')} Earnings Call")
        html, converter_meta = convert_transcript_to_html(raw_text, title=title)

        # Build metadata
        metadata = self._entry_to_metadata(entry)
        # Override with converter-extracted metadata if available
        if converter_meta.document_date and not metadata.document_date:
            metadata.document_date = converter_meta.document_date

        # Cache
        cache_path.write_text(html, encoding="utf-8")
        meta_path.write_text(json.dumps(self._metadata_to_dict(metadata), indent=2))

        return html, metadata

    def _entry_to_metadata(self, entry: dict[str, Any]) -> DocumentMetadata:
        """Convert an index entry to DocumentMetadata."""
        doc_date = None
        if entry.get("date"):
            try:
                doc_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        fiscal_year = None
        if entry.get("year"):
            try:
                fiscal_year = int(entry["year"])
            except (ValueError, TypeError):
                pass

        return DocumentMetadata(
            source_id=entry["source_id"],
            source=self.source_name,
            company_name=entry.get("company_name"),
            ticker=entry.get("ticker"),
            document_type="earnings_call",
            document_date=doc_date,
            title=entry.get("title"),
            fiscal_year=fiscal_year,
            fiscal_period=entry.get("quarter"),
            form_type="earnings_call",
        )

    @staticmethod
    def _metadata_to_dict(meta: DocumentMetadata) -> dict[str, Any]:
        """Serialize metadata to JSON-safe dict."""
        return {
            "source_id": meta.source_id,
            "source": meta.source,
            "company_name": meta.company_name,
            "ticker": meta.ticker,
            "document_type": meta.document_type,
            "document_date": meta.document_date.isoformat() if meta.document_date else None,
            "title": meta.title,
            "fiscal_year": meta.fiscal_year,
            "fiscal_period": meta.fiscal_period,
            "form_type": meta.form_type,
        }

    @staticmethod
    def _dict_to_metadata(d: dict[str, Any]) -> DocumentMetadata:
        """Deserialize metadata from JSON dict."""
        doc_date = None
        if d.get("document_date"):
            try:
                doc_date = date.fromisoformat(d["document_date"])
            except (ValueError, TypeError):
                pass

        return DocumentMetadata(
            source_id=d.get("source_id", ""),
            source=d.get("source", ""),
            company_name=d.get("company_name"),
            ticker=d.get("ticker"),
            document_type=d.get("document_type", "earnings_call"),
            document_date=doc_date,
            title=d.get("title"),
            fiscal_year=d.get("fiscal_year"),
            fiscal_period=d.get("fiscal_period"),
            form_type=d.get("form_type"),
        )
