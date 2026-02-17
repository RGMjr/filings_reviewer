"""
Document Source Protocol — Abstract interface for fetching documents.

Provides a common protocol for fetching documents from different sources
(SEC EDGAR, HuggingFace datasets, local files) with unified metadata.

Usage:
    >>> from src.infra.document_source import DocumentSource, DocumentMetadata
    >>> source = HuggingFaceTranscriptSource()
    >>> docs = source.list_available(ticker="SNOW")
    >>> html, metadata = source.fetch(docs[0].source_id)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass
class DocumentMetadata:
    """Metadata describing a document from any source."""

    # Identity
    source_id: str  # Unique ID within the source (e.g., HF row ID, accession number)
    source: str  # Source identifier (e.g., "sec_edgar", "huggingface:dataset_name")

    # Company info
    company_name: str | None = None
    ticker: str | None = None
    cik: str | None = None

    # Document info
    document_type: str = "sec_filing"  # sec_filing, earnings_call, investor_presentation
    document_date: date | None = None
    title: str | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None  # "FY", "Q1", "Q2", "Q3", "Q4"

    # Source-specific
    form_type: str | None = None  # SEC: "S-1", "10-K", etc. Transcript: "earnings_call"
    url: str | None = None  # Original URL if applicable


@runtime_checkable
class DocumentSource(Protocol):
    """Protocol for document sources."""

    def fetch(self, source_id: str) -> tuple[str, DocumentMetadata]:
        """
        Fetch a document by its source-specific ID.

        Args:
            source_id: Unique identifier within this source

        Returns:
            Tuple of (html_content, metadata)

        Raises:
            FileNotFoundError: If document not found
            ConnectionError: If source is unreachable
        """
        ...

    def list_available(
        self,
        ticker: str | None = None,
        company_name: str | None = None,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        """
        List available documents, optionally filtered.

        Args:
            ticker: Filter by stock ticker
            company_name: Filter by company name (substring match)
            limit: Maximum number of results

        Returns:
            List of DocumentMetadata for available documents
        """
        ...
