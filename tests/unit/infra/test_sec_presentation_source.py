"""
Unit tests for src/infra/sec_presentation_source.py.

Tests cover:
- Protocol compliance (DocumentSource)
- list_available: ticker resolution, exhibit filtering, empty results
- fetch: cache hit (idempotent), cache miss (download + convert + cache)
- _parse_source_id: valid and invalid formats
- _cache_paths: correct directory structure
- Error handling: ticker not found, PDF download failure, conversion failure
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.infra.document_source import DocumentMetadata, DocumentSource
from src.infra.sec_presentation_source import (
    SOURCE_NAME,
    SECPresentationSource,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def source(tmp_path: Path) -> SECPresentationSource:
    """Return a SECPresentationSource with a temp cache dir, mock SEC client,
    and a mock requests.Session so HTTP calls can be intercepted in tests."""
    mock_client = MagicMock()
    # Default _rate_limit does nothing
    mock_client._rate_limit.return_value = None

    src = SECPresentationSource(
        cache_dir=tmp_path / "presentations",
        sec_client=mock_client,
    )
    # Replace the real requests.Session with a MagicMock so tests can
    # control .get() return values without making network calls.
    src._session = MagicMock()
    return src


def _make_tickers_json(ticker: str = "CRM", cik: int = 1234567) -> dict:
    """Build a minimal company_tickers.json response body."""
    return {
        "0": {
            "cik_str": cik,
            "ticker": ticker,
            "title": "Salesforce Inc",
        }
    }


def _make_submissions(
    cik: str = "0001234567",
    accessions: list[str] | None = None,
    forms: list[str] | None = None,
    filing_dates: list[str] | None = None,
) -> dict:
    """Build a minimal submissions API response."""
    accessions = accessions or ["0001234567-24-000001"]
    forms = forms or ["8-K"]
    filing_dates = filing_dates or ["2024-01-15"]
    return {
        "name": "Salesforce Inc",
        "tickers": ["CRM"],
        "filings": {
            "recent": {
                "form": forms,
                "accessionNumber": accessions,
                "filingDate": filing_dates,
            },
            "files": [],
        },
    }


def _make_index_json(items: list[dict] | None = None) -> dict:
    """Build a minimal filing index.json response."""
    if items is None:
        items = [
            {
                "name": "investor_presentation.pdf",
                "type": "EX-99.1",
                "size": "1000000",
            }
        ]
    return {"directory": {"item": items}}


# ============================================================================
# Protocol compliance
# ============================================================================


def test_implements_document_source_protocol(source: SECPresentationSource) -> None:
    assert isinstance(source, DocumentSource)


# ============================================================================
# list_available
# ============================================================================


def test_list_available_no_ticker_returns_empty(source: SECPresentationSource) -> None:
    result = source.list_available()
    assert result == []


def test_list_available_ticker_not_found_returns_empty(
    source: SECPresentationSource,
) -> None:
    with patch.object(source, "_session") as mock_session:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}  # empty tickers map
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp

        result = source.list_available(ticker="ZZZZ")
        assert result == []


def test_list_available_returns_presentation_exhibits(
    source: SECPresentationSource, tmp_path: Path
) -> None:
    """list_available returns DocumentMetadata for matching PDF exhibits."""
    tickers_data = _make_tickers_json(ticker="CRM", cik=1234567)
    submissions_data = _make_submissions(
        cik="0001234567",
        accessions=["0001234567-24-000001"],
        forms=["8-K"],
        filing_dates=["2024-01-15"],
    )
    index_data = _make_index_json(
        items=[
            {
                "name": "investor_presentation.pdf",
                "type": "EX-99.1",
                "size": "1000000",
            }
        ]
    )

    # Mock session.get for tickers JSON
    mock_resp_tickers = MagicMock()
    mock_resp_tickers.json.return_value = tickers_data
    mock_resp_tickers.raise_for_status.return_value = None

    source._session.get.return_value = mock_resp_tickers

    # Mock SEC client _make_request for submissions + index
    def make_request_side_effect(url: str) -> dict:
        if "CIK" in url and "submissions" in url:
            return submissions_data
        if "index.json" in url:
            return index_data
        raise ValueError(f"Unexpected URL in test: {url}")

    source._sec_client._make_request.side_effect = make_request_side_effect

    results = source.list_available(ticker="CRM")

    assert len(results) == 1
    meta = results[0]
    assert isinstance(meta, DocumentMetadata)
    assert meta.ticker == "CRM"
    assert meta.document_type == "investor_presentation"
    assert meta.form_type == "8-K"
    assert meta.document_date == date(2024, 1, 15)
    assert "investor_presentation.pdf" in meta.source_id
    assert "1234567".zfill(10) in meta.source_id


def test_list_available_filters_non_pdf(source: SECPresentationSource) -> None:
    """Non-PDF exhibits are excluded even if exhibit type matches."""
    tickers_data = _make_tickers_json()
    submissions_data = _make_submissions()
    index_data = _make_index_json(
        items=[
            {"name": "exhibit99.htm", "type": "EX-99.1", "size": "50000"},
        ]
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = tickers_data
    mock_resp.raise_for_status.return_value = None
    source._session.get.return_value = mock_resp

    def make_request_side_effect(url: str) -> dict:
        if "CIK" in url:
            return submissions_data
        if "index.json" in url:
            return index_data
        raise ValueError(f"Unexpected URL: {url}")

    source._sec_client._make_request.side_effect = make_request_side_effect

    results = source.list_available(ticker="CRM")
    assert results == []


def test_list_available_filters_non_presentation_keyword(
    source: SECPresentationSource,
) -> None:
    """PDF exhibits whose filename contains no presentation keyword are excluded."""
    tickers_data = _make_tickers_json()
    submissions_data = _make_submissions()
    index_data = _make_index_json(
        items=[
            # PDF but no keyword in name
            {"name": "exhibit99.pdf", "type": "EX-99.1", "size": "200000"},
        ]
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = tickers_data
    mock_resp.raise_for_status.return_value = None
    source._session.get.return_value = mock_resp

    def make_request_side_effect(url: str) -> dict:
        if "CIK" in url:
            return submissions_data
        if "index.json" in url:
            return index_data
        raise ValueError(f"Unexpected URL: {url}")

    source._sec_client._make_request.side_effect = make_request_side_effect

    results = source.list_available(ticker="CRM")
    assert results == []


def test_list_available_filters_non_8k_forms(source: SECPresentationSource) -> None:
    """10-K or other form types are not scanned for exhibits."""
    tickers_data = _make_tickers_json()
    submissions_data = _make_submissions(forms=["10-K"])

    mock_resp = MagicMock()
    mock_resp.json.return_value = tickers_data
    mock_resp.raise_for_status.return_value = None
    source._session.get.return_value = mock_resp

    source._sec_client._make_request.return_value = submissions_data

    results = source.list_available(ticker="CRM")
    assert results == []


def test_list_available_respects_limit(source: SECPresentationSource) -> None:
    """list_available returns at most `limit` results."""
    tickers_data = _make_tickers_json()
    # Two 8-K filings, each with one matching exhibit
    submissions_data = _make_submissions(
        accessions=["0001234567-24-000001", "0001234567-24-000002"],
        forms=["8-K", "8-K"],
        filing_dates=["2024-01-15", "2024-02-20"],
    )
    index_data = _make_index_json(
        items=[
            {
                "name": "investor_presentation.pdf",
                "type": "EX-99.1",
                "size": "1000000",
            }
        ]
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = tickers_data
    mock_resp.raise_for_status.return_value = None
    source._session.get.return_value = mock_resp

    def make_request_side_effect(url: str) -> dict:
        if "CIK" in url:
            return submissions_data
        if "index.json" in url:
            return index_data
        raise ValueError(f"Unexpected URL: {url}")

    source._sec_client._make_request.side_effect = make_request_side_effect

    results = source.list_available(ticker="CRM", limit=1)
    assert len(results) == 1


# ============================================================================
# fetch — cache hit (idempotent)
# ============================================================================


def test_fetch_cache_hit_returns_cached_html(source: SECPresentationSource, tmp_path: Path) -> None:
    """fetch() returns cached HTML without downloading or converting."""
    cik = "0001234567"
    accession = "0001234567-24-000001"
    filename = "investor_presentation.pdf"
    source_id = f"{cik}/{accession}/{filename}"

    # Pre-populate cache
    ticker = "CRM"
    SECPresentationSource._cik_to_ticker_cache[cik] = ticker
    html_path, meta_path = source._cache_paths(ticker, accession, filename)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    cached_html = "<html><body>Cached presentation</body></html>"
    html_path.write_text(cached_html, encoding="utf-8")

    cached_meta = {
        "source_id": source_id,
        "source": SOURCE_NAME,
        "company_name": "Salesforce Inc",
        "ticker": "CRM",
        "cik": cik,
        "document_type": "investor_presentation",
        "document_date": "2024-01-15",
        "title": filename,
        "fiscal_year": None,
        "fiscal_period": None,
        "form_type": "8-K",
        "url": None,
    }
    meta_path.write_text(json.dumps(cached_meta), encoding="utf-8")

    with patch(
        "src.infra.sec_presentation_source.SECPresentationSource._download_pdf"
    ) as mock_download:
        html, meta = source.fetch(source_id)

    # No download should occur
    mock_download.assert_not_called()

    assert html == cached_html
    assert meta.source_id == source_id
    assert meta.ticker == "CRM"
    assert meta.document_date == date(2024, 1, 15)


# ============================================================================
# fetch — cache miss (download + convert + persist)
# ============================================================================


def test_fetch_cache_miss_downloads_converts_and_caches(
    source: SECPresentationSource, tmp_path: Path
) -> None:
    """fetch() downloads the PDF, converts it, and writes cache on first call."""
    cik = "0001234567"
    accession = "0001234567-24-000001"
    filename = "slides.pdf"
    source_id = f"{cik}/{accession}/{filename}"

    SECPresentationSource._cik_to_ticker_cache[cik] = "CRM"

    converted_html = "<html><body>Converted slides</body></html>"
    pdf_bytes = b"%PDF-1.4 fake content"

    mock_resp = MagicMock()
    mock_resp.content = pdf_bytes
    mock_resp.raise_for_status.return_value = None
    source._session.get.return_value = mock_resp

    source._sec_client.get_company_info.return_value = {
        "name": "Salesforce Inc",
        "tickers": ["CRM"],
    }

    _PATCH_TARGET = "src.infra.sec_presentation_source.convert_presentation_to_html"

    with patch(_PATCH_TARGET, return_value=converted_html):
        html, meta = source.fetch(source_id)

    assert html == converted_html
    assert meta.source_id == source_id
    assert meta.document_type == "investor_presentation"

    # Verify HTML and meta were written to cache
    html_path, meta_path = source._cache_paths("CRM", accession, filename)
    assert html_path.exists()
    assert meta_path.exists()
    assert html_path.read_text(encoding="utf-8") == converted_html

    # Second fetch should hit cache (no further HTTP calls)
    source._session.get.reset_mock()
    with patch(_PATCH_TARGET, return_value=converted_html) as mock_convert:
        html2, meta2 = source.fetch(source_id)

    mock_convert.assert_not_called()
    assert html2 == converted_html


def test_fetch_pdf_download_failure_raises_file_not_found(
    source: SECPresentationSource,
) -> None:
    """fetch() raises FileNotFoundError when PDF download fails and no cache."""
    cik = "0001234567"
    accession = "0001234567-24-000001"
    filename = "investor_presentation.pdf"
    source_id = f"{cik}/{accession}/{filename}"

    SECPresentationSource._cik_to_ticker_cache[cik] = "CRM"

    # Simulate download failure
    import requests as req_lib

    source._session.get.side_effect = req_lib.RequestException("connection refused")

    with pytest.raises(FileNotFoundError, match="Could not download PDF"):
        source.fetch(source_id)


def test_fetch_conversion_failure_propagates(
    source: SECPresentationSource,
) -> None:
    """fetch() re-raises exceptions from convert_presentation_to_html."""
    cik = "0001234567"
    accession = "0001234567-24-000001"
    filename = "presentation.pdf"
    source_id = f"{cik}/{accession}/{filename}"

    SECPresentationSource._cik_to_ticker_cache[cik] = "CRM"

    mock_resp = MagicMock()
    mock_resp.content = b"%PDF-1.4 content"
    mock_resp.raise_for_status.return_value = None
    source._session.get.return_value = mock_resp

    with patch(
        "src.infra.sec_presentation_source.convert_presentation_to_html",
        side_effect=RuntimeError("conversion error"),
    ):
        with pytest.raises(RuntimeError, match="conversion error"):
            source.fetch(source_id)


# ============================================================================
# _parse_source_id
# ============================================================================


def test_parse_source_id_valid() -> None:
    cik, accession, filename = SECPresentationSource._parse_source_id(
        "0001234567/0001234567-24-000001/investor_presentation.pdf"
    )
    assert cik == "0001234567"
    assert accession == "0001234567-24-000001"
    assert filename == "investor_presentation.pdf"


def test_parse_source_id_invalid_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Invalid source_id format"):
        SECPresentationSource._parse_source_id("no-slashes-here")


def test_parse_source_id_exactly_two_parts_raises() -> None:
    with pytest.raises(ValueError, match="Invalid source_id format"):
        SECPresentationSource._parse_source_id("cik/accession")


# ============================================================================
# _cache_paths
# ============================================================================


def test_cache_paths_structure(source: SECPresentationSource) -> None:
    """_cache_paths returns paths under cache_dir/TICKER/accession/filename.*"""
    html_path, meta_path = source._cache_paths("CRM", "0001234567-24-000001", "presentation.pdf")
    assert "CRM" in str(html_path)
    assert "0001234567-24-000001" in str(html_path)
    assert "presentation.pdf" in str(html_path)
    assert html_path.suffix == ".html"
    assert ".meta.json" in meta_path.name


# ============================================================================
# _exhibit_to_metadata
# ============================================================================


def test_exhibit_to_metadata_parses_date() -> None:
    exhibit = {
        "source_id": "0001234567/0001234567-24-000001/slides.pdf",
        "ticker": "CRM",
        "cik": "0001234567",
        "company_name": "Salesforce Inc",
        "form_type": "8-K",
        "filing_date": "2024-06-30",
        "exhibit_type": "EX-99.1",
        "filename": "slides.pdf",
        "accession_number": "0001234567-24-000001",
    }
    meta = SECPresentationSource._exhibit_to_metadata(exhibit, "Salesforce Inc")
    assert meta.document_date == date(2024, 6, 30)
    assert meta.ticker == "CRM"
    assert meta.document_type == "investor_presentation"


def test_exhibit_to_metadata_bad_date() -> None:
    exhibit = {
        "source_id": "0001234567/acc/file.pdf",
        "ticker": "CRM",
        "cik": "0001234567",
        "company_name": "Salesforce Inc",
        "form_type": "8-K",
        "filing_date": "not-a-date",
        "exhibit_type": "EX-99.1",
        "filename": "file.pdf",
        "accession_number": "acc",
    }
    meta = SECPresentationSource._exhibit_to_metadata(exhibit, None)
    assert meta.document_date is None


# ============================================================================
# Metadata serialisation round-trip
# ============================================================================


def test_metadata_roundtrip(source: SECPresentationSource, tmp_path: Path) -> None:
    original = DocumentMetadata(
        source_id="0001234567/0001234567-24-000001/presentation.pdf",
        source=SOURCE_NAME,
        company_name="Salesforce Inc",
        ticker="CRM",
        cik="0001234567",
        document_type="investor_presentation",
        document_date=date(2024, 3, 15),
        title="presentation.pdf",
        fiscal_year=2024,
        fiscal_period="Q4",
        form_type="8-K",
        url="https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001/presentation.pdf",
    )

    meta_path = tmp_path / "meta.json"
    meta_path.write_text(
        json.dumps(SECPresentationSource._metadata_to_dict(original)), encoding="utf-8"
    )
    restored = SECPresentationSource._load_cached_metadata(meta_path)

    assert restored.source_id == original.source_id
    assert restored.ticker == original.ticker
    assert restored.document_date == original.document_date
    assert restored.fiscal_year == original.fiscal_year
    assert restored.fiscal_period == original.fiscal_period
    assert restored.url == original.url
